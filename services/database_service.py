import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback and always release the SQLite file handle on context exit."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class DatabaseService:
    def __init__(self, database_path: str = "app_data/ai_master_pro.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachments_dir = self.database_path.parent / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            integrity_rows = connection.execute("PRAGMA quick_check").fetchall()
            if any(str(row[0]).lower() != "ok" for row in integrity_rows):
                raise sqlite3.DatabaseError("SQLite integrity check failed")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    attachment_name TEXT,
                    attachment_path TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chats_user_updated
                    ON chats(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_chat
                    ON messages(chat_id, id ASC);
                CREATE TABLE IF NOT EXISTS user_state (
                    user_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    user_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    memory_value TEXT NOT NULL,
                    source_chat_id INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, memory_key)
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_chat(self, user_id: str, title: str = "New chat") -> int:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO chats (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, title, now, now),
            )
            return int(cursor.lastrowid)

    def list_chats(self, user_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, updated_at FROM chats WHERE user_id = ? "
                "ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_state(self, user_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM user_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["state_json"])
        except json.JSONDecodeError:
            return None

    def save_user_state(self, user_id: str, state: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO user_state (user_id, state_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET state_json = excluded.state_json, "
                "updated_at = excluded.updated_at",
                (user_id, json.dumps(state), self._now()),
            )

    def get_messages(self, chat_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content, attachment_name, attachment_path, created_at "
                "FROM messages WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_attachments(self, user_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT messages.attachment_name, messages.attachment_path, messages.created_at, chats.title "
                "FROM messages JOIN chats ON chats.id = messages.chat_id "
                "WHERE chats.user_id = ? AND messages.attachment_path IS NOT NULL "
                "ORDER BY messages.id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_message(
        self,
        chat_id: int,
        role: str,
        content: str,
        attachment_name: str | None = None,
        attachment_path: str | None = None,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages (chat_id, role, content, attachment_name, attachment_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, role, content, attachment_name, attachment_path, now),
            )
            connection.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))

    def save_memory(
        self,
        user_id: str,
        key: str,
        value: str,
        source_chat_id: int | None = None,
    ) -> None:
        clean_value = " ".join(value.split())[:240]
        if not clean_value:
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (user_id, memory_key, memory_value, source_chat_id, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, memory_key) DO UPDATE SET "
                "memory_value = excluded.memory_value, source_chat_id = excluded.source_chat_id, "
                "updated_at = excluded.updated_at",
                (user_id, key, clean_value, source_chat_id, self._now()),
            )

    def learn_from_user_message(self, user_id: str, chat_id: int, message: str) -> None:
        patterns = [
            r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,40}?)(?:\s+and\b|[.!?,]|$)",
            r"\bcall me\s+([A-Za-z][A-Za-z .'-]{1,40}?)(?:\s+from\b|[.!?,]|$)",
            r"\bmera naam\s+([A-Za-z][A-Za-z .'-]{1,40}?)(?:\s+hai|[.!?,]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                self.save_memory(user_id, "preferred_name", match.group(1), chat_id)
                break

        preference = re.search(
            r"\b(?:i prefer|i like|please remember that)\s+(.{3,160})",
            message,
            flags=re.IGNORECASE,
        )
        if preference:
            self.save_memory(user_id, "latest_preference", preference.group(1), chat_id)

    def memory_context(
        self,
        user_id: str,
        current_chat_id: int | None,
        max_messages: int = 18,
    ) -> str:
        with self._connect() as connection:
            memory_rows = connection.execute(
                "SELECT memory_key, memory_value FROM memories WHERE user_id = ? "
                "ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            params: list[object] = [user_id]
            exclusion = ""
            if current_chat_id is not None:
                exclusion = "AND chats.id != ?"
                params.append(current_chat_id)
            params.append(max_messages)
            recent_rows = connection.execute(
                f"SELECT chats.title, messages.role, messages.content FROM messages "
                f"JOIN chats ON chats.id = messages.chat_id WHERE chats.user_id = ? {exclusion} "
                "ORDER BY messages.id DESC LIMIT ?",
                tuple(params),
            ).fetchall()

        sections: list[str] = []
        if memory_rows:
            profile = "\n".join(
                f"- {row['memory_key'].replace('_', ' ').title()}: {row['memory_value']}"
                for row in memory_rows
            )
            sections.append(f"Saved user profile:\n{profile}")
        if recent_rows:
            chronological = list(reversed(recent_rows))
            history = "\n".join(
                f"[{row['title']}] {row['role'].title()}: {row['content'][:500]}"
                for row in chronological
            )
            sections.append(f"Recent conversations from earlier chats:\n{history}")
        return "\n\n".join(sections)

    def set_chat_title(self, chat_id: int, title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
                (title[:60] or "New chat", self._now(), chat_id),
            )

    def delete_chat(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    def export_chats(self, user_id: str) -> bytes:
        """Return a portable, account-scoped JSON chat backup."""
        chats: list[dict] = []
        for chat in reversed(self.list_chats(user_id)):
            messages = []
            for message in self.get_messages(int(chat["id"])):
                messages.append(
                    {
                        "role": message["role"],
                        "content": message["content"],
                        "attachment_name": message.get("attachment_name"),
                        "created_at": message.get("created_at"),
                    }
                )
            chats.append(
                {
                    "title": chat["title"],
                    "updated_at": chat["updated_at"],
                    "messages": messages,
                }
            )
        payload = {
            "format": "ai-master-pro-chat-export",
            "version": 1,
            "exported_at": self._now(),
            "chats": chats,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def import_chats(self, user_id: str, raw_data: bytes, max_bytes: int = 5_000_000) -> int:
        """Import a validated JSON backup into the signed-in account."""
        if len(raw_data) > max_bytes:
            raise ValueError("The chat backup must be smaller than 5 MB.")
        try:
            payload = json.loads(raw_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("The selected file is not a valid chat backup.") from error
        if not isinstance(payload, dict) or payload.get("format") != "ai-master-pro-chat-export":
            raise ValueError("This file was not exported by AI Master Pro.")
        if payload.get("version") != 1 or not isinstance(payload.get("chats"), list):
            raise ValueError("This chat backup version is not supported.")

        imported = 0
        for chat in payload["chats"][:500]:
            if not isinstance(chat, dict) or not isinstance(chat.get("messages"), list):
                continue
            title = str(chat.get("title") or "Imported chat")[:60]
            chat_id = self.create_chat(user_id, title)
            saved_any = False
            for message in chat["messages"][:2000]:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                content = message.get("content")
                if role not in {"user", "assistant"} or not isinstance(content, str):
                    continue
                content = content.strip()[:100_000]
                if not content:
                    continue
                self.save_message(
                    chat_id,
                    role,
                    content,
                    str(message.get("attachment_name") or "")[:255] or None,
                    None,
                )
                saved_any = True
            if saved_any:
                imported += 1
            else:
                self.delete_chat(chat_id)
        return imported

    def delete_user_data(self, user_id: str) -> None:
        """Delete local chats, messages, memory, attachments metadata and usage."""
        attachment_paths = [
            item.get("attachment_path") for item in self.list_attachments(user_id)
        ]
        with self._connect() as connection:
            chat_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM chats WHERE user_id = ?", (user_id,)
                ).fetchall()
            ]
            if chat_ids:
                placeholders = ",".join("?" for _ in chat_ids)
                connection.execute(
                    f"DELETE FROM messages WHERE chat_id IN ({placeholders})",
                    tuple(chat_ids),
                )
            connection.execute("DELETE FROM chats WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM user_state WHERE user_id = ?", (user_id,))
        for stored_path in attachment_paths:
            if not stored_path:
                continue
            try:
                path = Path(stored_path).resolve()
                if path.is_file() and self.attachments_dir.resolve() in path.parents:
                    path.unlink()
            except OSError:
                pass

    def import_attachment(
        self,
        source_path: str | None,
        file_name: str,
        data: bytes | None = None,
    ) -> str:
        safe_name = "".join(
            character
            for character in Path(file_name).name
            if character.isalnum() or character in ".-_ "
        ).strip(" .")
        safe_name = safe_name[:180] or "attachment"
        destination = self.attachments_dir / f"{uuid4().hex}_{safe_name}"
        if source_path:
            shutil.copy2(source_path, destination)
        elif data is not None:
            destination.write_bytes(data)
        else:
            raise ValueError("The selected attachment data is unavailable.")
        return str(destination)


def open_database_resilient(
    database_path: str | Path,
) -> tuple[DatabaseService, Path | None]:
    """Open SQLite and preserve a corrupt database before creating a clean one.

    The corrupt file is renamed beside the database instead of being deleted,
    which makes the recovery reversible for support/debugging.
    """
    path = Path(database_path)
    try:
        return DatabaseService(str(path)), None
    except sqlite3.DatabaseError:
        if not path.exists():
            raise

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
    counter = 1
    while backup.exists():
        backup = path.with_name(
            f"{path.stem}.corrupt-{timestamp}-{counter}{path.suffix}"
        )
        counter += 1

    path.replace(backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.replace(Path(f"{backup}{suffix}"))

    return DatabaseService(str(path)), backup
