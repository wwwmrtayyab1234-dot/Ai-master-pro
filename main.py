from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir

import flet as ft

from config import (
    ADS_FOR_REQUEST_REFILL,
    AD_REQUEST_REFILL,
    AD_REWARD_CREDITS,
    APP_NAME,
    APP_SHARE_URL,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_URL,
    PRIVACY_POLICY_URL,
    SUPPORT_EMAIL,
    WHATSAPP_NUMBER,
)
TEXT = ft.Colors.ON_SURFACE
MUTED = ft.Colors.ON_SURFACE_VARIANT
BACKGROUND = ft.Colors.SURFACE
PANEL = ft.Colors.SURFACE_CONTAINER_LOW
BORDER = ft.Colors.OUTLINE_VARIANT
PRIMARY = "#5B8DEF"
PRIMARY_DARK = "#3568CB"
PURPLE = "#7C3AED"
RED = "#D92D20"
GREEN = "#067647"
WHITE = "#FFFFFF"


def prepare_app_data_directory(preferred_support_directory: str | None) -> tuple[Path, bool]:
    """Create a writable app directory, falling back without aborting startup."""
    candidates: list[Path] = []
    preferred_candidate: Path | None = None
    if preferred_support_directory:
        preferred_candidate = Path(preferred_support_directory) / "ai_master_pro"
        candidates.append(preferred_candidate)
    candidates.extend(
        [
            Path("app_data").resolve() / "ai_master_pro",
            Path(gettempdir()).resolve() / "ai_master_pro",
        ]
    )

    attempted: set[str] = set()
    last_error: OSError | None = None
    for index, candidate in enumerate(candidates):
        key = str(candidate)
        if key in attempted:
            continue
        attempted.add(key)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "recordings").mkdir(parents=True, exist_ok=True)
            return candidate, preferred_candidate is None or candidate != preferred_candidate
        except OSError as error:
            last_error = error
    raise RuntimeError("No writable application data directory is available.") from last_error


async def main(page: ft.Page) -> None:
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.spacing = 0
    page.window.width = 430
    page.window.height = 820
    page.window.min_width = 340
    page.window.min_height = 620
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=PRIMARY,
            secondary=PURPLE,
            surface="#FBFCFF",
        ),
        font_family="Arial",
    )
    page.dark_theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary="#8EAEFF",
            secondary="#B9A0FF",
            surface="#111318",
        ),
        font_family="Arial",
    )

    # Send the first control tree before importing optional SDKs or touching
    # storage. This dismisses Flet's native startup screen immediately even on
    # slower Android phones, while the remaining Python modules load lazily.
    first_paint_status = ft.Text(
        "Opening your workspace...",
        color="#718096",
        size=14,
        text_align=ft.TextAlign.CENTER,
    )
    root = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=WHITE, size=38),
                    width=72,
                    height=72,
                    bgcolor=PRIMARY,
                    border_radius=24,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Text(
                    APP_NAME,
                    color="#1E2A44",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.ProgressRing(color=PRIMARY, width=30, height=30),
                first_paint_status,
            ],
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        expand=True,
        bgcolor="#F7FAFF",
        alignment=ft.Alignment.CENTER,
    )
    page.add(root)
    page.update()
    await asyncio.sleep(0)

    # Optional and provider-specific packages are intentionally imported only
    # after the first frame is visible. Groq and Edge-TTS perform their own
    # provider imports lazily on first use as well.
    import flet_audio as fta
    from flet.auth.providers import GoogleOAuthProvider

    try:
        import flet_audio_recorder as far
    except ImportError:
        far = None

    try:
        import flet_secure_storage as fss
    except ImportError:
        fss = None

    from services.ad_service import create_native_ad, watch_rewarded_ad
    from services.crash_service import CrashProtector
    from services.database_service import open_database_resilient
    from services.error_service import friendly_error
    from services.firebase_auth_service import (
        EmailVerificationRequired,
        FirebaseAuthService,
        FirebaseUser,
        MAINTENANCE_MESSAGE,
        OFFLINE_MESSAGE,
        SessionExpired,
    )
    from services.gemini_service import analyze_attachment
    from services.groq_service import enhance_prompt, get_ai_reply
    from services.image_queue_service import ImageGenerationQueue
    from services.safety_service import RESTRICTED_RESPONSE, is_restricted_request
    from services.session_service import SessionService
    from services.usage_service import GateResult, UsageService
    from services.voice_service import (
        VOICE_OPTIONS,
        estimate_seconds,
        generate_voiceover,
    )

    file_picker = ft.FilePicker()
    share_service = ft.Share()
    connectivity = ft.Connectivity()
    storage_paths = ft.StoragePaths()
    shared_preferences = ft.SharedPreferences()
    secure_storage = fss.SecureStorage() if fss is not None else None
    audio_recorder = None
    if far is not None:
        audio_recorder = far.AudioRecorder(
            configuration=far.AudioRecorderConfiguration(
                encoder=far.AudioEncoder.WAV,
                channels=1,
                sample_rate=16000,
                suppress_noise=True,
                cancel_echo=True,
                auto_gain=True,
            )
        )
    page.services.extend(
        [file_picker, share_service, connectivity, storage_paths, shared_preferences]
    )
    if secure_storage is not None:
        page.services.append(secure_storage)
    if audio_recorder is not None:
        page.services.append(audio_recorder)

    support_directory: str | None = None
    try:
        support_directory = await storage_paths.get_application_support_directory()
    except Exception:
        support_directory = None
    app_data_directory, storage_fallback_used = prepare_app_data_directory(
        support_directory
    )
    recordings_directory = app_data_directory / "recordings"

    try:
        crash_protector = CrashProtector(app_data_directory / "logs")
    except OSError:
        emergency_logs = Path(gettempdir()).resolve() / "ai_master_pro_logs"
        crash_protector = CrashProtector(emergency_logs)
        storage_fallback_used = True
    crash_protector.install(asyncio.get_running_loop())

    database_recovery_backup: Path | None = None
    database_recovery_mode = False
    try:
        database, database_recovery_backup = await asyncio.to_thread(
            open_database_resilient,
            app_data_directory / "ai_master_pro.db",
        )
    except Exception as error:
        crash_protector.capture_exception(error, "Primary local database startup failed")
        emergency_directory = Path(gettempdir()).resolve() / "ai_master_pro_recovery"
        emergency_directory.mkdir(parents=True, exist_ok=True)
        database, database_recovery_backup = await asyncio.to_thread(
            open_database_resilient,
            emergency_directory / "ai_master_pro.db",
        )
        database_recovery_mode = True

    if database_recovery_backup is not None:
        crash_protector.capture_message(
            f"A corrupt SQLite database was preserved at {database_recovery_backup}."
        )
    if storage_fallback_used:
        crash_protector.capture_message(
            f"Application storage fallback is active: {app_data_directory}."
        )
    usage = UsageService(database)
    firebase_auth = FirebaseAuthService()
    image_queue = ImageGenerationQueue()
    session_store = SessionService(secure_storage, shared_preferences)

    current_user: FirebaseUser | None = None
    current_chat_id: int | None = None
    selected_chat_attachment: dict[str, str] | None = None
    selected_analysis_attachment: dict[str, str] | None = None
    audio_player: fta.Audio | None = None
    sidebar_open = False
    is_offline = False
    google_oauth_in_progress = False

    def toast(message: str, error: bool = False) -> None:
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message, color=WHITE),
                bgcolor=RED if error else "#1E293B",
                show_close_icon=True,
            )
        )

    async def ensure_online() -> bool:
        if is_offline:
            toast(OFFLINE_MESSAGE, error=True)
            return False
        try:
            states = await connectivity.get_connectivity()
            if states and ft.ConnectivityType.NONE in states:
                toast(OFFLINE_MESSAGE, error=True)
                return False
        except Exception:
            # Provider calls still have their own transport error mapping.
            pass
        return True

    def field(**kwargs) -> ft.TextField:
        return ft.TextField(
            border_radius=14,
            border_color=BORDER,
            focused_border_color=PRIMARY,
            filled=True,
            bgcolor=PANEL,
            text_style=ft.TextStyle(color=TEXT, size=15),
            **kwargs,
        )

    def heading(icon, title: str, subtitle: str) -> ft.Column:
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(icon, color=PRIMARY_DARK, size=22),
                            width=40,
                            height=40,
                            bgcolor="#EAF1FF",
                            border_radius=12,
                            alignment=ft.Alignment.CENTER,
                        ),
                        ft.Text(title, color=TEXT, size=21, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=10,
                ),
                ft.Text(subtitle, color=MUTED, size=13),
            ],
            spacing=5,
        )

    def user_bubble(text: str, attachment_name: str | None = None) -> ft.Row:
        controls: list[ft.Control] = []
        if attachment_name:
            controls.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.ATTACH_FILE, color=MUTED, size=15),
                        ft.Text(
                            attachment_name,
                            color=MUTED,
                            size=12,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                    ],
                    spacing=5,
                )
            )
        controls.append(ft.Text(text, color=TEXT, size=15, selectable=True))
        return ft.Row(
            controls=[
                ft.Container(expand=2),
                ft.Container(
                    content=ft.Column(controls=controls, spacing=6),
                    expand=8,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    padding=ft.Padding.symmetric(horizontal=15, vertical=11),
                    border_radius=18,
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def ai_message(text: str) -> ft.Row:
        return ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.SMART_TOY_OUTLINED, color=WHITE, size=17),
                    width=34,
                    height=34,
                    bgcolor=PRIMARY,
                    border_radius=12,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Container(
                    content=ft.Text(text, color=TEXT, size=15, selectable=True),
                    expand=True,
                    padding=ft.Padding.only(top=6),
                ),
            ],
            spacing=11,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    offline_banner = ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, color=WHITE, size=18),
                ft.Text(OFFLINE_MESSAGE, color=WHITE, size=13, expand=True),
            ],
            spacing=8,
        ),
        bgcolor="#B54708",
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        visible=False,
    )

    # ------------------------- Usage and rewarded ads -------------------------
    plan_badge = ft.Text(size=12, weight=ft.FontWeight.BOLD)
    credit_badge = ft.Text(size=12, color=TEXT)
    settings_plan = ft.Text(size=15, weight=ft.FontWeight.BOLD, color=TEXT)
    settings_credits = ft.Text(size=13, color=MUTED)
    settings_requests = ft.Text(size=13, color=MUTED)
    settings_images = ft.Text(size=13, color=MUTED)
    settings_voice = ft.Text(size=13, color=MUTED)
    settings_ads = ft.Text(size=13, color=MUTED)
    settings_reset = ft.Text(size=12, color=MUTED)

    def refresh_usage_ui() -> None:
        snapshot = usage.snapshot()
        plan_badge.value = snapshot["plan"]
        plan_badge.color = PURPLE if usage.premium else TEXT
        credit_badge.value = f"Credits: {snapshot['credits']}"
        settings_plan.value = f"Current plan: {snapshot['plan']}"
        settings_credits.value = f"Available credits: {snapshot['credits']}"
        settings_requests.value = snapshot["requests"]
        settings_images.value = snapshot["images"]
        settings_voice.value = snapshot["voice"]
        settings_ads.value = snapshot["ads"]
        reset_at = snapshot.get("reset_at")
        if reset_at:
            try:
                local_reset = datetime.fromisoformat(reset_at).astimezone()
                settings_reset.value = f"Rolling reset: {local_reset.strftime('%d %b, %I:%M %p')}"
            except ValueError:
                settings_reset.value = "Rolling reset: 24 hours after this window began"

    async def handle_gate_denied(gate: GateResult) -> None:
        if gate.reason not in {"credits", "request_limit"}:
            toast(gate.message, error=True)
            return

        reward_title = ft.Text("Watch Ad To Get Free Credits")
        reward_message = ft.Text(gate.message, color=TEXT)
        reward_progress_text = ft.Text("", color=MUTED, size=12)
        reward_button = ft.Button(
            "Watch rewarded ad",
            icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
            bgcolor=PRIMARY,
            color=WHITE,
        )
        reward_progress = ft.ProgressRing(visible=False, width=18, height=18)
        dialog = ft.AlertDialog(
            modal=True,
            title=reward_title,
            content=ft.Column(
                controls=[reward_message, reward_progress_text],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton("Not now", on_click=lambda _e: page.pop_dialog()),
                reward_progress,
                reward_button,
            ],
        )

        def update_reward_progress() -> None:
            snapshot = usage.snapshot()
            reward_progress_text.value = (
                f"Ad pack progress: {snapshot['ads']}. Complete all "
                f"{ADS_FOR_REQUEST_REFILL} ads to receive {AD_REWARD_CREDITS} credits. "
                "No partial reward is granted."
            )

        async def watch_reward(_event=None) -> None:
            reward_button.disabled = True
            reward_progress.visible = True
            page.update()
            try:
                verified = await watch_rewarded_ad(page)
                if not verified:
                    toast(
                        "The ad was not completed, so no progress was recorded. Please try again.",
                        error=True,
                    )
                    return
                reward = await usage.record_rewarded_ad()
                refresh_usage_ui()
                update_reward_progress()
                if reward["pack_completed"]:
                    toast(
                        f"All {ADS_FOR_REQUEST_REFILL} ads completed. "
                        f"{AD_REWARD_CREDITS} credits and {AD_REQUEST_REFILL} "
                        "extra requests were added."
                    )
                    dialog.open = False
                else:
                    remaining = reward["ads_needed"]
                    reward_message.value = (
                        f"Watch {remaining} more ad{'s' if remaining != 1 else ''} "
                        f"to receive {AD_REWARD_CREDITS} credits."
                    )
            except Exception as error:
                toast(friendly_error(error), error=True)
            finally:
                reward_button.disabled = False
                reward_progress.visible = False
                page.update()

        reward_button.on_click = watch_reward
        update_reward_progress()
        page.show_dialog(dialog)

    async def import_picked_file() -> dict[str, str] | None:
        files = await file_picker.pick_files(allow_multiple=False, with_data=True)
        if not files:
            return None
        picked = files[0]
        stored_path = database.import_attachment(
            picked.path,
            picked.name,
            getattr(picked, "bytes", None),
        )
        return {"name": picked.name, "path": stored_path}

    # ------------------------- Chat -------------------------
    conversation: list[dict[str, str]] = []
    chat_busy = False
    recording_chat_input = False
    recording_path: str | None = None
    chat_history = ft.ListView(
        expand=True,
        spacing=18,
        padding=ft.Padding.symmetric(horizontal=8, vertical=16),
        auto_scroll=True,
    )
    chat_sidebar_items = ft.ListView(expand=True, spacing=4)
    chat_search = field(
        hint_text="Search chats",
        prefix_icon=ft.Icons.SEARCH,
        height=46,
        dense=True,
    )
    sidebar_email = ft.Text("", color=MUTED, size=12, max_lines=1)
    attachment_status = ft.Text("", color=PRIMARY_DARK, size=12, visible=False)
    speech_status = ft.Text("", color=RED, size=12, visible=False)

    chat_loading = ft.Row(
        controls=[
            ft.ProgressRing(width=15, height=15, stroke_width=2, color=PRIMARY),
            ft.Text("AI is thinking...", size=12, color=MUTED),
        ],
        spacing=8,
        visible=False,
    )
    chat_input = ft.TextField(
        hint_text="Message AI Master Pro...",
        border=ft.InputBorder.NONE,
        text_style=ft.TextStyle(color=TEXT, size=15),
        hint_style=ft.TextStyle(color=MUTED, size=15),
        multiline=True,
        min_lines=1,
        max_lines=4,
        shift_enter=True,
        expand=True,
    )
    chat_send = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD,
        icon_color=WHITE,
        bgcolor=PRIMARY,
        width=42,
        height=42,
        tooltip="Send",
    )
    chat_attach = ft.IconButton(
        icon=ft.Icons.ATTACH_FILE,
        icon_color=MUTED,
        tooltip="Attach an image, PDF, document, audio, or video",
    )
    chat_mic = ft.IconButton(
        icon=ft.Icons.MIC_NONE_ROUNDED,
        icon_color=MUTED,
        tooltip="Speech to text",
    )

    def toggle_sidebar(_event=None, value: bool | None = None) -> None:
        nonlocal sidebar_open
        sidebar_open = (not sidebar_open) if value is None else value
        sidebar_panel.visible = sidebar_open
        sidebar_scrim.visible = sidebar_open
        page.update()

    def refresh_chat_sidebar(_event=None) -> None:
        chat_sidebar_items.controls.clear()
        if current_user is None:
            return
        query = (chat_search.value or "").strip().lower()
        for chat in database.list_chats(current_user.uid):
            if query and query not in chat["title"].lower():
                continue
            chat_id = int(chat["id"])
            selected = chat_id == current_chat_id

            def open_chat(_event=None, selected_id=chat_id) -> None:
                load_chat(selected_id)
                toggle_sidebar(value=False)

            def remove_chat(_event=None, selected_id=chat_id) -> None:
                delete_chat(selected_id)

            chat_sidebar_items.controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                chat["title"],
                                color=TEXT,
                                size=13,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=MUTED,
                                icon_size=17,
                                tooltip="Delete chat",
                                on_click=remove_chat,
                            ),
                        ],
                        spacing=2,
                    ),
                    padding=ft.Padding.only(left=10, top=3, bottom=3),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH if selected else PANEL,
                    border_radius=10,
                    on_click=open_chat,
                )
            )

    def load_chat(chat_id: int) -> None:
        nonlocal current_chat_id
        current_chat_id = chat_id
        conversation.clear()
        chat_history.controls.clear()
        for message in database.get_messages(chat_id):
            if message["role"] == "user":
                chat_history.controls.append(
                    user_bubble(message["content"], message["attachment_name"])
                )
            else:
                chat_history.controls.append(ai_message(message["content"]))
            conversation.append({"role": message["role"], "content": message["content"]})
        if not chat_history.controls:
            chat_history.controls.append(
                ai_message("Hello! How can I help you create something today?")
            )
        refresh_chat_sidebar()
        page.update()

    def create_new_chat(_event=None) -> None:
        nonlocal current_chat_id, selected_chat_attachment
        if current_user is None:
            return
        current_chat_id = database.create_chat(current_user.uid)
        selected_chat_attachment = None
        attachment_status.visible = False
        load_chat(current_chat_id)
        toggle_sidebar(value=False)

    def delete_chat(chat_id: int) -> None:
        nonlocal current_chat_id
        database.delete_chat(chat_id)
        remaining = database.list_chats(current_user.uid) if current_user else []
        if current_chat_id == chat_id:
            if remaining:
                load_chat(int(remaining[0]["id"]))
            else:
                current_chat_id = None
                create_new_chat()
        else:
            refresh_chat_sidebar()
            page.update()

    async def pick_chat_attachment(_event=None) -> None:
        nonlocal selected_chat_attachment
        try:
            selected_chat_attachment = await import_picked_file()
            if selected_chat_attachment:
                attachment_status.value = f"Attached: {selected_chat_attachment['name']}"
                attachment_status.visible = True
                page.update()
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def toggle_speech_to_text(_event=None) -> None:
        nonlocal recording_chat_input, recording_path
        if chat_busy:
            return
        if audio_recorder is None:
            toast(
                "Speech to text needs the flet-audio-recorder package. Run setup_windows.bat again.",
                error=True,
            )
            return
        try:
            if not recording_chat_input:
                if not await audio_recorder.has_permission():
                    toast("Microphone permission is required for speech to text.", error=True)
                    return
                recording_path = str(
                    recordings_directory
                    / f"speech_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.wav"
                )
                started = await audio_recorder.start_recording(recording_path)
                if not started:
                    raise RuntimeError("The microphone could not start recording.")
                recording_chat_input = True
                chat_mic.icon = ft.Icons.STOP_ROUNDED
                chat_mic.icon_color = RED
                speech_status.value = "Listening... tap the stop button when you finish."
                speech_status.visible = True
                page.update()
                return

            recorded_path = await audio_recorder.stop_recording()
            recording_chat_input = False
            chat_mic.icon = ft.Icons.MIC_NONE_ROUNDED
            chat_mic.icon_color = MUTED
            speech_status.value = "Transcribing speech..."
            page.update()
            final_path = recorded_path or recording_path
            if not final_path:
                raise RuntimeError("No microphone recording was created.")
            transcript = await asyncio.to_thread(
                analyze_attachment,
                final_path,
                "Transcribe this recording accurately. Return only the spoken words, without a title or explanation.",
                "",
            )
            chat_input.value = transcript.strip()
            speech_status.visible = False
            page.update()
            await chat_input.focus()
        except Exception as error:
            recording_chat_input = False
            chat_mic.icon = ft.Icons.MIC_NONE_ROUNDED
            chat_mic.icon_color = MUTED
            speech_status.visible = False
            toast(friendly_error(error), error=True)
            page.update()

    async def send_chat(_event=None) -> None:
        nonlocal chat_busy, selected_chat_attachment
        prompt = (chat_input.value or "").strip()
        if not prompt or chat_busy or current_user is None:
            return
        if current_chat_id is None:
            create_new_chat()
        if current_chat_id is None:
            return
        if not await ensure_online():
            return

        gate = usage.gate("chat")
        if not gate.allowed:
            await handle_gate_denied(gate)
            return

        chat_busy = True
        chat_input.value = ""
        chat_input.disabled = True
        chat_send.disabled = True
        chat_mic.disabled = True
        chat_loading.visible = True
        attachment_name = selected_chat_attachment["name"] if selected_chat_attachment else None
        attachment_path = selected_chat_attachment["path"] if selected_chat_attachment else None
        chat_history.controls.append(user_bubble(prompt, attachment_name))
        conversation.append({"role": "user", "content": prompt})
        database.save_message(current_chat_id, "user", prompt, attachment_name, attachment_path)
        database.learn_from_user_message(current_user.uid, current_chat_id, prompt)
        if len(conversation) == 1:
            database.set_chat_title(current_chat_id, " ".join(prompt.split())[:48])
        selected_chat_attachment = None
        attachment_status.visible = False
        page.update()

        reply: str
        completed = False
        try:
            if is_restricted_request(prompt):
                reply = RESTRICTED_RESPONSE
                completed = True
            else:
                memory = database.memory_context(current_user.uid, current_chat_id)
                if attachment_path:
                    reply = await asyncio.to_thread(
                        analyze_attachment,
                        attachment_path,
                        prompt,
                        memory,
                    )
                else:
                    reply = await get_ai_reply(
                        conversation,
                        premium=usage.premium,
                        memory_context=memory,
                    )
                completed = True
            conversation.append({"role": "assistant", "content": reply})
            database.save_message(current_chat_id, "assistant", reply)
            if completed:
                await usage.record("chat", gate)
        except Exception as error:
            reply = friendly_error(error)
        finally:
            chat_history.controls.append(ai_message(reply))
            chat_loading.visible = False
            chat_input.disabled = False
            chat_send.disabled = False
            chat_mic.disabled = False
            chat_busy = False
            refresh_chat_sidebar()
            refresh_usage_ui()
            page.update()
            await chat_input.focus()

    chat_search.on_change = refresh_chat_sidebar
    chat_input.on_submit = send_chat
    chat_send.on_click = send_chat
    chat_attach.on_click = pick_chat_attachment
    chat_mic.on_click = toggle_speech_to_text

    sidebar_panel = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=PRIMARY),
                                ft.Text(APP_NAME, color=TEXT, size=17, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=8,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color=TEXT,
                            tooltip="Close sidebar",
                            on_click=toggle_sidebar,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                sidebar_email,
                ft.Button(
                    "New chat",
                    icon=ft.Icons.EDIT_SQUARE,
                    bgcolor=PRIMARY,
                    color=WHITE,
                    on_click=create_new_chat,
                ),
                chat_search,
                ft.Text("CHAT HISTORY", color=MUTED, size=11),
                chat_sidebar_items,
                ft.Divider(color=BORDER),
                ft.Button(
                    "Settings",
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    on_click=lambda _e: open_settings(),
                ),
                ft.Button(
                    "Log out",
                    icon=ft.Icons.LOGOUT,
                    on_click=lambda _e: page.run_task(logout),
                ),
            ],
            spacing=10,
            expand=True,
        ),
        width=300,
        bgcolor=PANEL,
        padding=14,
        shadow=ft.BoxShadow(blur_radius=22, color="#33000000", offset=ft.Offset(4, 0)),
        visible=False,
        left=0,
        top=0,
        bottom=0,
    )
    sidebar_scrim = ft.Container(
        expand=True,
        bgcolor="#44000000",
        visible=False,
        on_click=lambda _e: toggle_sidebar(value=False),
        left=0,
        top=0,
        right=0,
        bottom=0,
    )
    chat_main = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.MENU,
                            icon_color=TEXT,
                            tooltip="Open chat history",
                            on_click=toggle_sidebar,
                        ),
                        heading(
                            ft.Icons.CHAT_BUBBLE_OUTLINE,
                            "AI Chat",
                            "Smart chat with cross-chat memory",
                        ),
                        ft.IconButton(
                            icon=ft.Icons.EDIT_SQUARE,
                            icon_color=TEXT,
                            tooltip="New chat",
                            on_click=create_new_chat,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                chat_history,
                chat_loading,
                attachment_status,
                speech_status,
                ft.Container(
                    content=ft.Row(
                        controls=[chat_attach, chat_mic, chat_input, chat_send],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    border=ft.Border.all(1, BORDER),
                    border_radius=24,
                    padding=ft.Padding.only(left=3, right=5, top=5, bottom=5),
                    bgcolor=BACKGROUND,
                ),
            ],
            spacing=12,
            expand=True,
        ),
        padding=ft.Padding.symmetric(horizontal=14, vertical=14),
        bgcolor=BACKGROUND,
        expand=True,
    )
    chat_view = ft.Stack(controls=[chat_main, sidebar_scrim, sidebar_panel], expand=True)

    # ------------------------- Image Studio -------------------------
    image_busy = False
    enhance_busy = False
    generated_image_bytes: bytes | None = None
    generated_image_mime = "image/png"
    image_prompt = field(
        label="Describe your image",
        hint_text="Example: A cinematic city at sunrise",
        multiline=True,
        min_lines=3,
        max_lines=7,
    )
    image_status = ft.Text("Ready — 10 credits per image", color=MUTED, size=12)
    image_loading = ft.ProgressRing(visible=False, color=PRIMARY)
    enhance_loading = ft.ProgressRing(visible=False, color=PURPLE, width=18, height=18)
    image_button = ft.Button(
        "Generate image — 10 credits",
        icon=ft.Icons.IMAGE,
        bgcolor=PRIMARY,
        color=WHITE,
    )
    enhance_button = ft.Button(
        "Enhance prompt",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor="#F3F0FF",
        color=PURPLE,
        elevation=0,
    )
    image_output = ft.Image(
        src="",
        visible=False,
        border_radius=16,
        fit=ft.BoxFit.CONTAIN,
        error_content=ft.Text("The generated image could not be displayed.", color=RED),
    )
    view_image_button = ft.OutlinedButton(
        "View image",
        icon=ft.Icons.FULLSCREEN_ROUNDED,
        visible=False,
    )
    download_image_button = ft.Button(
        "Download image",
        icon=ft.Icons.DOWNLOAD_ROUNDED,
        bgcolor="#EEF4FF",
        color=PRIMARY_DARK,
        visible=False,
    )
    image_native_ad_slot = ft.Container(
        visible=False,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=18,
        padding=8,
    )
    image_placeholder = ft.Column(
        controls=[
            ft.Icon(ft.Icons.IMAGE_OUTLINED, color=MUTED, size=58),
            ft.Text("Your generated image will appear here", color=MUTED, size=13),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
    )

    def refresh_native_ad_slot() -> None:
        native_ad = create_native_ad(page)
        if native_ad is None:
            image_native_ad_slot.visible = False
            image_native_ad_slot.content = None
            return
        image_native_ad_slot.content = ft.Column(
            controls=[
                ft.Text("Sponsored", color=MUTED, size=10),
                native_ad,
            ],
            spacing=4,
            tight=True,
        )
        image_native_ad_slot.visible = True

    def decode_generated_image(source: str) -> tuple[bytes, str]:
        header, encoded = source.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError("The generated image data is invalid.")
        mime = header[5:].split(";", 1)[0]
        return base64.b64decode(encoded, validate=True), mime

    def view_generated_image(_event=None) -> None:
        if not image_output.src or generated_image_bytes is None:
            toast("Generate an image first.", error=True)
            return
        viewer = ft.InteractiveViewer(
            content=ft.Image(
                src=image_output.src,
                fit=ft.BoxFit.CONTAIN,
                border_radius=12,
            ),
            min_scale=0.5,
            max_scale=5,
        )
        width = max(280, min(760, (page.width or 430) - 36))
        height = max(320, min(720, (page.height or 820) - 150))
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Generated image"),
                content=ft.Container(
                    content=viewer,
                    width=width,
                    height=height,
                    bgcolor="#101318",
                    border_radius=16,
                    alignment=ft.Alignment.CENTER,
                ),
                actions=[ft.TextButton("Close", on_click=lambda _e: page.pop_dialog())],
            )
        )

    async def download_generated_image(_event=None) -> None:
        if generated_image_bytes is None:
            toast("Generate an image first.", error=True)
            return
        extension = "jpg" if generated_image_mime in {"image/jpeg", "image/jpg"} else "png"
        file_name = f"ai_master_pro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
        try:
            saved_path = await file_picker.save_file(
                dialog_title="Save generated image",
                file_name=file_name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=[extension],
                src_bytes=generated_image_bytes,
            )
            if saved_path and not page.web and not page.platform.is_mobile():
                Path(saved_path).write_bytes(generated_image_bytes)
            if page.web or saved_path:
                toast("Image saved successfully.")
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def run_enhancer(_event=None) -> None:
        nonlocal enhance_busy
        prompt = (image_prompt.value or "").strip()
        if not prompt or enhance_busy:
            toast("Enter an image prompt first.", error=True)
            return
        if not await ensure_online():
            return
        gate = usage.gate("enhance")
        if not gate.allowed:
            await handle_gate_denied(gate)
            return
        enhance_busy = True
        enhance_button.disabled = True
        enhance_loading.visible = True
        page.update()
        try:
            if is_restricted_request(prompt):
                await usage.record("enhance", gate)
                toast(RESTRICTED_RESPONSE, error=True)
            else:
                image_prompt.value = await enhance_prompt(prompt, premium=usage.premium)
                await usage.record("enhance", gate)
                toast("Prompt enhanced successfully.")
        except Exception as error:
            toast(friendly_error(error), error=True)
        finally:
            enhance_busy = False
            enhance_button.disabled = False
            enhance_loading.visible = False
            refresh_usage_ui()
            page.update()

    async def generate_image(_event=None) -> None:
        nonlocal image_busy, generated_image_bytes, generated_image_mime
        prompt = (image_prompt.value or "").strip()
        if not prompt or image_busy:
            toast("Enter an image prompt first.", error=True)
            return
        if not await ensure_online():
            return
        gate = usage.gate("image")
        if not gate.allowed:
            await handle_gate_denied(gate)
            return
        if is_restricted_request(prompt):
            await usage.record("image", gate)
            refresh_usage_ui()
            toast(RESTRICTED_RESPONSE, error=True)
            page.update()
            return
        image_busy = True
        image_button.disabled = True
        image_loading.visible = True
        image_output.visible = False
        view_image_button.visible = False
        download_image_button.visible = False
        image_placeholder.visible = False
        refresh_native_ad_slot()
        queue_position = image_queue.pending_count + 1
        image_status.value = f"Queued request #{queue_position}. Generating safely..."
        page.update()
        try:
            source = await image_queue.generate(prompt, usage.premium)
            generated_image_bytes, generated_image_mime = decode_generated_image(source)
            image_output.src = source
            image_output.visible = True
            view_image_button.visible = True
            download_image_button.visible = True
            image_status.value = "Image generated successfully."
            await usage.record("image", gate)
        except Exception as error:
            generated_image_bytes = None
            image_placeholder.visible = True
            image_status.value = "Generation could not be completed."
            toast(friendly_error(error), error=True)
        finally:
            image_busy = False
            image_button.disabled = False
            image_loading.visible = False
            refresh_usage_ui()
            page.update()

    enhance_button.on_click = run_enhancer
    image_button.on_click = generate_image
    view_image_button.on_click = view_generated_image
    download_image_button.on_click = download_generated_image
    image_preview_container = ft.Container(
        content=ft.Stack(
            controls=[
                ft.Container(content=image_placeholder, alignment=ft.Alignment.CENTER),
                ft.Container(content=image_output, alignment=ft.Alignment.CENTER),
            ],
            expand=True,
        ),
        height=360,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=18,
        padding=10,
    )
    image_view = ft.Container(
        content=ft.ListView(
            controls=[
                heading(
                    ft.Icons.IMAGE_OUTLINED,
                    "Image Studio",
                    "Maximum 5 images per rolling 24 hours; safe queued generation",
                ),
                image_prompt,
                ft.Row(controls=[enhance_button, enhance_loading], wrap=True),
                ft.Row(
                    controls=[image_button, image_loading],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                image_status,
                image_native_ad_slot,
                image_preview_container,
                ft.Row(
                    controls=[view_image_button, download_image_button],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
            ],
            spacing=14,
            expand=True,
            padding=16,
        ),
        bgcolor=BACKGROUND,
        expand=True,
    )

    # ------------------------- Voice Studio -------------------------
    voice_busy = False
    voice_input = field(
        label="Voiceover script",
        hint_text="1 second of generated voice costs 1 credit",
        multiline=True,
        min_lines=4,
        max_lines=8,
    )
    voice_dropdown = ft.Dropdown(
        value="edge_male",
        label="Select voice",
        options=[
            ft.DropdownOption(key=key, text=config["name"])
            for key, config in VOICE_OPTIONS.items()
        ],
        border_radius=14,
        border_color=BORDER,
        focused_border_color=PRIMARY,
        expand=True,
    )
    voice_loading = ft.ProgressRing(visible=False, color=PRIMARY)
    voice_status = ft.Text("No audio generated yet.", color=MUTED, size=13)
    voice_generate = ft.Button(
        "Generate voice",
        icon=ft.Icons.GRAPHIC_EQ,
        bgcolor=PRIMARY,
        color=WHITE,
    )
    voice_play = ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="Play", disabled=True)
    voice_pause = ft.IconButton(icon=ft.Icons.PAUSE, tooltip="Pause", disabled=True)

    async def play_audio(_event=None) -> None:
        if audio_player is not None:
            await audio_player.play()

    async def pause_audio(_event=None) -> None:
        if audio_player is not None:
            await audio_player.pause()

    async def generate_voice(_event=None) -> None:
        nonlocal voice_busy, audio_player
        text = (voice_input.value or "").strip()
        voice_key = voice_dropdown.value
        if not text or not voice_key or voice_busy:
            toast("Enter a script and select a voice.", error=True)
            return
        if not await ensure_online():
            return
        config = VOICE_OPTIONS[voice_key]
        if config["premium"] and not usage.premium:
            toast("This ElevenLabs voice requires the premium plan.", error=True)
            return
        seconds = estimate_seconds(text)
        estimated_units = len(text) if usage.premium else seconds
        gate = usage.gate("voice", estimated_units)
        if not gate.allowed:
            await handle_gate_denied(gate)
            return
        if is_restricted_request(text):
            await usage.record("voice", gate, estimated_units)
            refresh_usage_ui()
            toast(RESTRICTED_RESPONSE, error=True)
            page.update()
            return
        voice_busy = True
        voice_generate.disabled = True
        voice_input.disabled = True
        voice_dropdown.disabled = True
        voice_loading.visible = True
        voice_status.value = f"Generating approximately {seconds} seconds of voice..."
        page.update()
        try:
            audio_bytes, voice_name, actual_seconds = await generate_voiceover(
                text,
                voice_key,
                premium_user=usage.premium,
            )
            actual_units = len(text) if usage.premium else actual_seconds
            final_gate = usage.gate("voice", actual_units)
            if not final_gate.allowed:
                await handle_gate_denied(final_gate)
                return
            if audio_player is not None:
                try:
                    await audio_player.release()
                except Exception:
                    pass
            audio_player = fta.Audio(src=audio_bytes, autoplay=False, volume=1.0)
            page.services.append(audio_player)
            voice_status.value = (
                f"Ready: {voice_name}; {actual_seconds} seconds; "
                f"{actual_seconds if not usage.premium else len(text)} credits/units used"
            )
            voice_play.disabled = False
            voice_pause.disabled = False
            await usage.record("voice", final_gate, actual_units)
            page.update()
            await audio_player.play()
        except Exception as error:
            voice_status.value = "Voice generation could not be completed."
            toast(friendly_error(error), error=True)
        finally:
            voice_busy = False
            voice_generate.disabled = False
            voice_input.disabled = False
            voice_dropdown.disabled = False
            voice_loading.visible = False
            refresh_usage_ui()
            page.update()

    voice_generate.on_click = generate_voice
    voice_play.on_click = play_audio
    voice_pause.on_click = pause_audio
    voice_view = ft.Container(
        content=ft.Column(
            controls=[
                heading(
                    ft.Icons.MIC_NONE,
                    "Voice Studio",
                    "1 second = 1 credit; maximum 60 seconds per rolling window",
                ),
                voice_input,
                voice_dropdown,
                ft.Row(
                    controls=[voice_generate, voice_loading],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("Audio player", color=TEXT, weight=ft.FontWeight.BOLD),
                            voice_status,
                            ft.Row(
                                controls=[voice_play, voice_pause],
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=PANEL,
                    border=ft.Border.all(1, BORDER),
                    border_radius=18,
                    padding=20,
                ),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=16,
        bgcolor=BACKGROUND,
        expand=True,
    )

    # ------------------------- Multimodal Analysis -------------------------
    analysis_busy = False
    analysis_prompt = field(
        label="What should AI analyze?",
        hint_text="Example: Summarize this video and list the key moments",
        multiline=True,
        min_lines=2,
        max_lines=5,
    )
    analysis_file_status = ft.Text("No file selected.", color=MUTED, size=13)
    analysis_loading = ft.ProgressRing(visible=False, color=PRIMARY)
    pick_analysis_button = ft.Button("Choose file", icon=ft.Icons.UPLOAD_FILE)
    analyze_button = ft.Button(
        "Analyze with Gemini",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor=PRIMARY,
        color=WHITE,
    )
    analysis_messages = ft.ListView(
        controls=[
            ai_message(
                "Choose an image, PDF, document, audio file, or video. Your analysis result will appear here in a readable conversation view."
            )
        ],
        expand=True,
        spacing=18,
        padding=ft.Padding.symmetric(horizontal=8, vertical=14),
        auto_scroll=True,
    )

    async def pick_analysis_file(_event=None) -> None:
        nonlocal selected_analysis_attachment
        try:
            selected_analysis_attachment = await import_picked_file()
            if selected_analysis_attachment:
                analysis_file_status.value = f"Selected: {selected_analysis_attachment['name']}"
                page.update()
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def run_analysis(_event=None) -> None:
        nonlocal analysis_busy
        if analysis_busy:
            return
        if selected_analysis_attachment is None:
            toast("Choose an image, PDF, document, audio file, or video first.", error=True)
            return
        if not await ensure_online():
            return
        prompt = (analysis_prompt.value or "").strip() or (
            "Analyze this file and explain the important information."
        )
        gate = usage.gate("analysis")
        if not gate.allowed:
            await handle_gate_denied(gate)
            return
        analysis_busy = True
        analyze_button.disabled = True
        pick_analysis_button.disabled = True
        analysis_loading.visible = True
        analysis_messages.controls.append(
            user_bubble(prompt, selected_analysis_attachment["name"])
        )
        page.update()

        completed = False
        try:
            if is_restricted_request(prompt):
                result = RESTRICTED_RESPONSE
                completed = True
            else:
                memory = (
                    database.memory_context(current_user.uid, current_chat_id)
                    if current_user
                    else ""
                )
                result = await asyncio.to_thread(
                    analyze_attachment,
                    selected_analysis_attachment["path"],
                    prompt,
                    memory,
                )
                completed = True
            analysis_messages.controls.append(ai_message(result))
            analysis_chat_id = database.create_chat(
                current_user.uid,
                f"Analysis: {selected_analysis_attachment['name']}"[:60],
            )
            database.save_message(
                analysis_chat_id,
                "user",
                prompt,
                selected_analysis_attachment["name"],
                selected_analysis_attachment["path"],
            )
            database.save_message(analysis_chat_id, "assistant", result)
            if completed:
                await usage.record("analysis", gate)
        except Exception as error:
            analysis_messages.controls.append(ai_message(friendly_error(error)))
        finally:
            analysis_busy = False
            analyze_button.disabled = False
            pick_analysis_button.disabled = False
            analysis_loading.visible = False
            refresh_chat_sidebar()
            refresh_usage_ui()
            page.update()

    pick_analysis_button.on_click = pick_analysis_file
    analyze_button.on_click = run_analysis
    analysis_view = ft.Container(
        content=ft.Column(
            controls=[
                heading(
                    ft.Icons.DOCUMENT_SCANNER_OUTLINED,
                    "Multimodal Analysis",
                    "Images, PDFs, documents, audio, and video with Gemini",
                ),
                analysis_prompt,
                ft.Row(
                    controls=[pick_analysis_button, analyze_button, analysis_loading],
                    wrap=True,
                ),
                analysis_file_status,
                ft.Container(
                    content=analysis_messages,
                    expand=True,
                    bgcolor=PANEL,
                    border=ft.Border.all(1, BORDER),
                    border_radius=18,
                    padding=8,
                ),
            ],
            spacing=13,
            expand=True,
        ),
        padding=16,
        bgcolor=BACKGROUND,
        expand=True,
    )

    # ------------------------- Settings -------------------------
    dark_mode_switch = ft.Switch(value=False)

    privacy_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("AI Master Pro Privacy Policy"),
        content=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Effective date: July 13, 2026", weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "AI Master Pro processes account data, prompts, selected files, local chat history, preferences, and per-account usage data to provide its features. Files and prompts are sent only to the AI provider required for the feature you choose."
                    ),
                    ft.Text(
                        "Microphone audio is captured only after you tap the microphone button and grant permission. Camera and location permissions are not requested."
                    ),
                    ft.Text(
                        "You can export chats or delete your Firebase account and local chats, memory, attachments, and usage data from Settings."
                    ),
                    ft.Text(
                        "The complete production policy is included as privacy_policy.html. A public HTTPS URL and real support email must be configured before Google Play submission.",
                        color=MUTED,
                    ),
                ],
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=520,
            height=360,
        ),
        actions=[ft.Button("Close", on_click=lambda _e: page.pop_dialog())],
    )

    async def open_external_url(url: str, missing_message: str) -> None:
        if not url:
            toast(missing_message, error=True)
            return
        try:
            await page.launch_url(url)
        except Exception as error:
            toast(friendly_error(error), error=True)

    def change_theme(event) -> None:
        page.theme_mode = ft.ThemeMode.DARK if event.control.value else ft.ThemeMode.LIGHT
        page.update()

    dark_mode_switch.on_change = change_theme

    async def open_privacy_policy(_event=None) -> None:
        if PRIVACY_POLICY_URL and "your-public-domain.example" not in PRIVACY_POLICY_URL:
            await open_external_url(PRIVACY_POLICY_URL, "")
        else:
            page.show_dialog(privacy_dialog)

    async def contact_support(_event=None) -> None:
        if SUPPORT_EMAIL:
            await open_external_url(
                f"mailto:{SUPPORT_EMAIL}?subject=AI%20Master%20Pro%20Support",
                "",
            )
        elif WHATSAPP_NUMBER:
            await open_external_url(
                f"https://wa.me/{WHATSAPP_NUMBER}?text=AI%20Master%20Pro%20Support",
                "",
            )
        else:
            toast("Add SUPPORT_EMAIL or WHATSAPP_NUMBER to .env.", error=True)

    async def send_feedback(_event=None) -> None:
        if not SUPPORT_EMAIL:
            toast("Add SUPPORT_EMAIL to .env to receive feedback.", error=True)
            return
        await open_external_url(
            f"mailto:{SUPPORT_EMAIL}?subject=AI%20Master%20Pro%20Feedback",
            "",
        )

    async def share_app(_event=None) -> None:
        text = "Try AI Master Pro — an all-in-one AI studio."
        if APP_SHARE_URL:
            text = f"{text}\n{APP_SHARE_URL}"
        try:
            await share_service.share_text(
                text,
                title=APP_NAME,
                subject="Try AI Master Pro",
            )
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def export_chats(_event=None) -> None:
        if current_user is None:
            return
        try:
            payload = database.export_chats(current_user.uid)
            file_name = f"ai_master_pro_chats_{datetime.now().strftime('%Y%m%d')}.json"
            await file_picker.save_file(
                dialog_title="Export AI Master Pro chats",
                file_name=file_name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                src_bytes=payload,
            )
            toast("Chat export created successfully.")
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def import_chats(_event=None) -> None:
        if current_user is None:
            return
        try:
            files = await file_picker.pick_files(
                dialog_title="Import AI Master Pro chats",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                allow_multiple=False,
                with_data=True,
            )
            if not files:
                return
            picked = files[0]
            raw = getattr(picked, "bytes", None)
            if raw is None and picked.path:
                raw = Path(picked.path).read_bytes()
            if raw is None:
                raise ValueError("The selected backup could not be read.")
            count = database.import_chats(current_user.uid, raw)
            refresh_chat_sidebar()
            toast(f"Imported {count} chat{'s' if count != 1 else ''} successfully.")
            page.update()
        except Exception as error:
            toast(friendly_error(error), error=True)

    async def delete_account_and_data() -> None:
        nonlocal current_user
        if current_user is None:
            return
        delete_dialog.open = False
        page.update()
        try:
            if current_user.refresh_token:
                refreshed = await asyncio.to_thread(
                    firebase_auth.refresh_session,
                    current_user.refresh_token,
                    current_user.email,
                )
                current_user = refreshed
                await session_store.save(refreshed)
            uid = current_user.uid
            await asyncio.to_thread(firebase_auth.delete_account, current_user.id_token)
            database.delete_user_data(uid)
            await session_store.clear()
            await logout(clear_session=False)
            toast("Your account and local data were deleted.")
        except Exception as error:
            toast(friendly_error(error), error=True)

    delete_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Delete account and data?"),
        content=ft.Text(
            "This permanently deletes your Firebase account and local chats, memory, attachments, and usage data from this device."
        ),
        actions=[
            ft.TextButton("Cancel", on_click=lambda _e: page.pop_dialog()),
            ft.Button(
                "Delete permanently",
                bgcolor=RED,
                color=WHITE,
                on_click=lambda _e: page.run_task(delete_account_and_data),
            ),
        ],
    )

    def settings_tile(icon, title: str, subtitle: str, on_click=None, trailing=None) -> ft.Container:
        controls: list[ft.Control] = [
            ft.Container(
                content=ft.Icon(icon, color=PRIMARY_DARK, size=21),
                width=42,
                height=42,
                bgcolor="#EAF1FF",
                border_radius=12,
                alignment=ft.Alignment.CENTER,
            ),
            ft.Column(
                controls=[
                    ft.Text(title, color=TEXT, size=15, weight=ft.FontWeight.W_600),
                    ft.Text(subtitle, color=MUTED, size=12),
                ],
                spacing=2,
                expand=True,
            ),
        ]
        controls.append(trailing or ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED))
        return ft.Container(
            content=ft.Row(controls=controls, spacing=12),
            padding=12,
            border=ft.Border(bottom=ft.BorderSide(1, BORDER)),
            on_click=on_click,
        )

    settings_view = ft.Container(
        content=ft.Column(
            controls=[
                heading(ft.Icons.SETTINGS_OUTLINED, "Settings", "Account, appearance, privacy, and backups"),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            settings_plan,
                            settings_credits,
                            settings_requests,
                            settings_images,
                            settings_voice,
                            settings_ads,
                            settings_reset,
                        ],
                        spacing=6,
                    ),
                    bgcolor=PANEL,
                    border=ft.Border.all(1, BORDER),
                    border_radius=18,
                    padding=16,
                ),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            settings_tile(
                                ft.Icons.PRIVACY_TIP_OUTLINED,
                                "Privacy Policy",
                                "Read the policy or open its public page",
                                open_privacy_policy,
                            ),
                            settings_tile(
                                ft.Icons.CONTACT_SUPPORT_OUTLINED,
                                "Contact Us",
                                "Email or WhatsApp support",
                                contact_support,
                            ),
                            settings_tile(
                                ft.Icons.RATE_REVIEW_OUTLINED,
                                "Feedback",
                                "Send suggestions and report problems",
                                send_feedback,
                            ),
                            settings_tile(
                                ft.Icons.SHARE_OUTLINED,
                                "Share App",
                                "Share AI Master Pro with friends",
                                share_app,
                            ),
                            settings_tile(
                                ft.Icons.DARK_MODE_OUTLINED,
                                "Dark Mode / Light Mode",
                                "Change the app appearance",
                                trailing=dark_mode_switch,
                            ),
                            settings_tile(
                                ft.Icons.FILE_UPLOAD_OUTLINED,
                                "Chat Import",
                                "Restore chats from an AI Master Pro JSON backup",
                                import_chats,
                            ),
                            settings_tile(
                                ft.Icons.FILE_DOWNLOAD_OUTLINED,
                                "Chat Export",
                                "Save your chats as a portable JSON backup",
                                export_chats,
                            ),
                        ],
                        spacing=0,
                    ),
                    border=ft.Border.all(1, BORDER),
                    border_radius=18,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
                ft.Button(
                    "Log out",
                    icon=ft.Icons.LOGOUT,
                    on_click=lambda _e: page.run_task(logout),
                ),
                ft.Button(
                    "Delete Account & Local Data",
                    icon=ft.Icons.DELETE_FOREVER_OUTLINED,
                    color=RED,
                    on_click=lambda _e: page.show_dialog(delete_dialog),
                ),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=16,
        bgcolor=BACKGROUND,
        expand=True,
    )

    # ------------------------- App shell -------------------------
    views = [chat_view, image_view, voice_view, analysis_view, settings_view]
    content_area = ft.Container(content=views[0], expand=True, bgcolor=BACKGROUND)
    body_frame = ft.Container(content=content_area, width=900, expand=True)

    def change_view(event) -> None:
        content_area.content = views[event.control.selected_index]
        if event.control.selected_index == 4:
            refresh_usage_ui()
        page.update()

    def open_settings() -> None:
        navigation_bar.selected_index = 4
        content_area.content = settings_view
        toggle_sidebar(value=False)
        refresh_usage_ui()
        page.update()

    navigation_bar = ft.NavigationBar(
        selected_index=0,
        on_change=change_view,
        bgcolor=BACKGROUND,
        indicator_color="#DCE8FF",
        destinations=[
            ft.NavigationBarDestination(
                icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                selected_icon=ft.Icons.CHAT_BUBBLE,
                label="Chat",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.IMAGE_OUTLINED,
                selected_icon=ft.Icons.IMAGE,
                label="Image",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.MIC_NONE,
                selected_icon=ft.Icons.MIC,
                label="Voice",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.DOCUMENT_SCANNER_OUTLINED,
                selected_icon=ft.Icons.DOCUMENT_SCANNER,
                label="Analyze",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Settings",
            ),
        ],
    )
    app_header = ft.Container(
        content=ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=PRIMARY, size=25),
                        ft.Text(APP_NAME, color=TEXT, size=18, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=8,
                    expand=True,
                ),
                ft.Container(
                    content=plan_badge,
                    bgcolor=PANEL,
                    border_radius=10,
                    padding=ft.Padding.symmetric(horizontal=9, vertical=5),
                ),
                credit_badge,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=60,
        padding=ft.Padding.symmetric(horizontal=16),
        border=ft.Border(bottom=ft.BorderSide(1, BORDER)),
        bgcolor=BACKGROUND,
    )
    app_shell = ft.SafeArea(
        content=ft.Column(
            controls=[
                offline_banner,
                app_header,
                ft.Row(
                    controls=[body_frame],
                    alignment=ft.MainAxisAlignment.CENTER,
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        ),
        expand=True,
    )

    # ------------------------- Authentication -------------------------
    auth_mode = "signin"
    login_email = ft.TextField(
        hint_text="Your email",
        prefix_icon=ft.Icons.MAIL_OUTLINE_ROUNDED,
        keyboard_type=ft.KeyboardType.EMAIL,
        border_radius=14,
        border_color="#D6E0EE",
        focused_border_color=PRIMARY,
        filled=True,
        bgcolor="#F5F8FD",
        text_style=ft.TextStyle(color="#1E2A44", size=15),
        hint_style=ft.TextStyle(color="#7B879A"),
        height=54,
    )
    login_password = ft.TextField(
        hint_text="Password",
        prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED,
        password=True,
        can_reveal_password=True,
        border_radius=14,
        border_color="#D6E0EE",
        focused_border_color=PRIMARY,
        filled=True,
        bgcolor="#F5F8FD",
        text_style=ft.TextStyle(color="#1E2A44", size=15),
        hint_style=ft.TextStyle(color="#7B879A"),
        height=54,
    )
    login_status = ft.Text("", color=RED, size=12, visible=False, text_align=ft.TextAlign.CENTER)
    login_busy = ft.ProgressRing(visible=False, width=20, height=20, color=PRIMARY)
    primary_auth_button = ft.Button(
        "Sign in",
        icon=ft.Icons.ARROW_FORWARD_ROUNDED,
        bgcolor=PRIMARY,
        color=WHITE,
        height=54,
    )
    auth_toggle_text = ft.Text("Don't have an account?", color="#718096", size=13)
    auth_toggle_button = ft.TextButton("Sign up")

    def set_login_status(message: str = "", error: bool = True) -> None:
        login_status.value = message
        login_status.color = RED if error else GREEN
        login_status.visible = bool(message)

    async def finish_login(user: FirebaseUser, persist: bool = True) -> None:
        nonlocal current_user
        current_user = user
        if persist:
            await session_store.save(user)
        await usage.initialize(user.uid)
        sidebar_email.value = user.email
        existing = database.list_chats(user.uid)
        if existing:
            load_chat(int(existing[0]["id"]))
        else:
            create_new_chat()
        refresh_chat_sidebar()
        refresh_usage_ui()
        show_app()

    async def sign_in(_event=None) -> None:
        email = (login_email.value or "").strip()
        password = login_password.value or ""
        if not email or not password:
            set_login_status("Enter your email and password.")
            page.update()
            return
        login_busy.visible = True
        primary_auth_button.disabled = True
        set_login_status()
        page.update()
        try:
            user = await asyncio.to_thread(firebase_auth.sign_in, email, password)
            await finish_login(user)
        except Exception as error:
            set_login_status(friendly_error(error))
        finally:
            login_busy.visible = False
            primary_auth_button.disabled = False
            page.update()

    async def sign_up(_event=None) -> None:
        email = (login_email.value or "").strip()
        password = login_password.value or ""
        login_busy.visible = True
        primary_auth_button.disabled = True
        set_login_status()
        page.update()
        try:
            await asyncio.to_thread(firebase_auth.sign_up, email, password)
            set_login_status(
                "Verification email sent. Open the link in your email, then sign in.",
                error=False,
            )
            set_auth_mode("signin")
            login_password.value = ""
        except Exception as error:
            set_login_status(friendly_error(error))
        finally:
            login_busy.visible = False
            primary_auth_button.disabled = False
            page.update()

    async def primary_auth_action(_event=None) -> None:
        if auth_mode == "signup":
            await sign_up()
        else:
            await sign_in()

    def set_auth_mode(mode: str) -> None:
        nonlocal auth_mode
        auth_mode = mode
        set_login_status()
        if auth_mode == "signup":
            primary_auth_button.content = "Create account"
            auth_toggle_text.value = "Already have an account?"
            auth_toggle_button.content = "Sign in"
        else:
            primary_auth_button.content = "Sign in"
            auth_toggle_text.value = "Don't have an account?"
            auth_toggle_button.content = "Sign up"
        page.update()

    def toggle_auth_mode(_event=None) -> None:
        set_auth_mode("signup" if auth_mode == "signin" else "signin")

    async def forgot_password(_event=None) -> None:
        email = (login_email.value or "").strip()
        if not email:
            set_login_status("Enter your email to receive a reset link.")
            page.update()
            return
        try:
            await asyncio.to_thread(firebase_auth.send_password_reset, email)
            set_login_status("Password reset email sent.", error=False)
        except Exception as error:
            set_login_status(friendly_error(error))
        page.update()

    async def complete_google_oauth(event) -> None:
        nonlocal google_oauth_in_progress
        if not google_oauth_in_progress:
            return
        try:
            if event.error:
                description = event.error_description or event.error
                raise RuntimeError(description or "Google sign-in was cancelled.")
            authorization = page.auth
            if authorization is None:
                raise RuntimeError("Google sign-in did not return an authorization.")
            token = await authorization.get_token()
            if token is None or not token.access_token:
                raise RuntimeError("Google sign-in did not return an access token.")
            user = await asyncio.to_thread(
                firebase_auth.sign_in_with_google_access_token,
                token.access_token,
                GOOGLE_OAUTH_REDIRECT_URL,
            )
            await finish_login(user)
        except Exception as error:
            set_login_status(friendly_error(error))
        finally:
            google_oauth_in_progress = False
            login_busy.visible = False
            google_button.disabled = False
            page.update()

    async def google_sign_in(_event=None) -> None:
        nonlocal google_oauth_in_progress
        if google_oauth_in_progress:
            return
        login_busy.visible = True
        google_button.disabled = True
        set_login_status()
        page.update()
        is_mobile = False
        try:
            is_mobile = not page.web and page.platform.is_mobile()
        except (AttributeError, TypeError):
            pass
        if is_mobile:
            if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
                set_login_status(
                    "Google sign-in needs GOOGLE_OAUTH_CLIENT_ID and "
                    "GOOGLE_OAUTH_CLIENT_SECRET in .env."
                )
                login_busy.visible = False
                google_button.disabled = False
                page.update()
                return
            try:
                google_oauth_in_progress = True
                provider = GoogleOAuthProvider(
                    client_id=GOOGLE_OAUTH_CLIENT_ID,
                    client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
                    redirect_url=GOOGLE_OAUTH_REDIRECT_URL,
                )
                await page.login(provider)
            except Exception as error:
                google_oauth_in_progress = False
                login_busy.visible = False
                google_button.disabled = False
                set_login_status(friendly_error(error))
                page.update()
            return
        try:
            user = await asyncio.to_thread(firebase_auth.sign_in_with_google)
            await finish_login(user)
        except Exception as error:
            set_login_status(friendly_error(error))
        finally:
            login_busy.visible = False
            google_button.disabled = False
            page.update()

    async def logout(clear_session: bool = True) -> None:
        nonlocal current_user, current_chat_id, selected_chat_attachment, selected_analysis_attachment
        if clear_session:
            await session_store.clear()
        current_user = None
        current_chat_id = None
        selected_chat_attachment = None
        selected_analysis_attachment = None
        conversation.clear()
        chat_history.controls.clear()
        chat_sidebar_items.controls.clear()
        login_password.value = ""
        set_login_status()
        show_login()

    primary_auth_button.on_click = primary_auth_action
    auth_toggle_button.on_click = toggle_auth_mode

    google_button = ft.OutlinedButton(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text("G", color="#4285F4", weight=ft.FontWeight.BOLD),
                    width=28,
                    height=28,
                    bgcolor="#EEF4FF",
                    border_radius=9,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Text(
                    "Continue with Google",
                    color="#1E2A44",
                    size=15,
                    weight=ft.FontWeight.W_600,
                    expand=True,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(width=28),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=54,
        on_click=google_sign_in,
    )
    login_card = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=WHITE, size=42),
                    width=76,
                    height=76,
                    bgcolor=PRIMARY,
                    border_radius=24,
                    alignment=ft.Alignment.CENTER,
                    shadow=ft.BoxShadow(blur_radius=24, color="#445B8DEF", offset=ft.Offset(0, 8)),
                ),
                ft.Text(
                    "Welcome to\nAI Master Pro",
                    color="#1E2A44",
                    size=29,
                    weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER,
                    height=72,
                ),
                ft.Text(
                    "Your personal AI companion",
                    color="#7B879A",
                    size=14,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=4),
                login_email,
                login_password,
                ft.Row(
                    controls=[
                        ft.Container(expand=True),
                        ft.TextButton("Forgot password?", on_click=forgot_password),
                    ]
                ),
                login_status,
                ft.Row(
                    controls=[primary_auth_button, login_busy],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                google_button,
                ft.Row(
                    controls=[auth_toggle_text, auth_toggle_button],
                    spacing=2,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Email accounts require verification before first sign-in.",
                    color="#8794A6",
                    size=11,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=420,
        bgcolor="#FCFDFF",
        border=ft.Border.all(1, "#E2E8F0"),
        border_radius=30,
        padding=32,
        shadow=ft.BoxShadow(blur_radius=42, color="#263B5B22", offset=ft.Offset(0, 16)),
    )
    login_hero = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.AUTO_AWESOME, color=WHITE, size=34),
                    width=64,
                    height=64,
                    bgcolor="#6B8DF6",
                    border_radius=20,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Text(
                    "Create, analyze, and grow\nwith one AI workspace.",
                    color="#173054",
                    size=36,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Chat, images, voice, documents, and video analysis — designed for creators.",
                    color="#54657C",
                    size=16,
                    width=460,
                ),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=GREEN),
                        ft.Text("Secure sign-in and private per-account usage", color="#35506F"),
                    ]
                ),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=GREEN),
                        ft.Text("Responsive on every mobile screen", color="#35506F"),
                    ]
                ),
            ],
            spacing=20,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        expand=True,
        padding=48,
    )
    login_layout = ft.Row(
        controls=[
            login_hero,
            ft.Container(
                content=login_card,
                alignment=ft.Alignment.CENTER,
                expand=True,
                padding=24,
            ),
        ],
        expand=True,
        spacing=0,
    )
    login_screen = ft.SafeArea(
        content=ft.Container(
            content=login_layout,
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
                colors=["#F8FBFF", "#EEF4FF", "#F7F4FF"],
            ),
        ),
        expand=True,
    )

    startup_screen = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=WHITE, size=42),
                    width=78,
                    height=78,
                    bgcolor=PRIMARY,
                    border_radius=26,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Text(APP_NAME, color="#1E2A44", size=26, weight=ft.FontWeight.BOLD),
                ft.ProgressRing(color=PRIMARY),
                ft.Text("Starting securely...", color="#718096"),
            ],
            spacing=18,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        expand=True,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=["#F8FBFF", "#EEF4FF", "#F7F4FF"],
        ),
        alignment=ft.Alignment.CENTER,
    )
    offline_screen = ft.Container(
        content=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, color="#B54708", size=52),
                    ft.Text(
                        OFFLINE_MESSAGE,
                        color="#1E2A44",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        "AI Master Pro needs an internet connection for sign-in and AI features.",
                        color="#718096",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Button(
                        "Try again",
                        icon=ft.Icons.REFRESH,
                        bgcolor=PRIMARY,
                        color=WHITE,
                        on_click=lambda _e: page.run_task(bootstrap),
                    ),
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=390,
            bgcolor="#FCFDFF",
            border_radius=26,
            border=ft.Border.all(1, "#E2E8F0"),
            padding=30,
        ),
        expand=True,
        bgcolor="#F5F8FD",
        alignment=ft.Alignment.CENTER,
        padding=20,
    )
    maintenance_screen = ft.Container(
        content=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.CONSTRUCTION_ROUNDED, color=PRIMARY_DARK, size=52),
                    ft.Text(
                        MAINTENANCE_MESSAGE,
                        color="#1E2A44",
                        size=19,
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Button(
                        "Try again",
                        icon=ft.Icons.REFRESH,
                        bgcolor=PRIMARY,
                        color=WHITE,
                        on_click=lambda _e: page.run_task(bootstrap),
                    ),
                ],
                spacing=18,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=390,
            bgcolor="#FCFDFF",
            border_radius=26,
            border=ft.Border.all(1, "#E2E8F0"),
            padding=30,
        ),
        expand=True,
        bgcolor="#F5F8FD",
        alignment=ft.Alignment.CENTER,
        padding=20,
    )

    def show_startup() -> None:
        page.navigation_bar = None
        root.content = startup_screen
        page.update()

    def show_app() -> None:
        page.navigation_bar = navigation_bar
        root.content = app_shell
        page.update()

    def show_login() -> None:
        page.navigation_bar = None
        root.content = login_screen
        page.update()

    def show_offline() -> None:
        page.navigation_bar = None
        root.content = offline_screen
        page.update()

    def show_maintenance() -> None:
        page.navigation_bar = None
        root.content = maintenance_screen
        page.update()

    async def probe_connectivity() -> None:
        """Refresh the offline indicator without blocking the first screen."""
        nonlocal is_offline
        try:
            states = await asyncio.wait_for(
                connectivity.get_connectivity(), timeout=2.0
            )
            is_offline = bool(states and ft.ConnectivityType.NONE in states)
            offline_banner.visible = is_offline
            if is_offline and current_user is None:
                show_offline()
            else:
                page.update()
        except Exception:
            # Provider requests still display their own friendly network error.
            return

    async def refresh_saved_session(saved: dict) -> None:
        """Validate a cached login after the local workspace is already open."""
        nonlocal current_user
        try:
            refreshed = await asyncio.wait_for(
                asyncio.to_thread(
                    firebase_auth.refresh_session,
                    saved["refresh_token"],
                    saved.get("email", ""),
                ),
                timeout=12.0,
            )
            if current_user is not None and current_user.uid == saved.get("uid"):
                current_user = refreshed
                await session_store.save(refreshed)
        except (SessionExpired, EmailVerificationRequired):
            if current_user is not None and current_user.uid == saved.get("uid"):
                await logout(clear_session=True)
                set_login_status(
                    "Your saved session expired. Please sign in again."
                )
                page.update()
        except Exception:
            # A temporary network/provider failure must not throw the user back
            # to login. The cached secure session remains available locally.
            return

    async def bootstrap() -> None:
        show_startup()
        try:
            saved = await asyncio.wait_for(session_store.load(), timeout=4.0)
        except Exception:
            saved = None
        if not saved:
            show_login()
            page.run_task(probe_connectivity)
            return

        # SecureStorage already proves that this device signed in previously.
        # Restore local chats/credits immediately, then refresh the short-lived
        # Firebase token in the background instead of blocking startup for up
        # to the provider's network timeout.
        cached_user = FirebaseUser(
            uid=str(saved.get("uid", "")),
            email=str(saved.get("email", "")),
            id_token="",
            refresh_token=str(saved.get("refresh_token", "")),
            email_verified=True,
        )
        if not cached_user.uid or not cached_user.refresh_token:
            await session_store.clear()
            show_login()
            page.run_task(probe_connectivity)
            return
        await finish_login(cached_user, persist=False)
        page.run_task(refresh_saved_session, saved)
        page.run_task(probe_connectivity)

    def resize_layout(_event=None) -> None:
        width = page.width or page.window.width or 430
        height = page.height or page.window.height or 820
        login_hero.visible = width >= 820
        login_card.width = max(300, min(420, width - (36 if width < 820 else 80)))
        login_card.padding = 22 if width < 390 else 32
        sidebar_panel.width = max(260, min(310, width * 0.86))
        body_frame.width = min(1000, width)
        app_header.padding = ft.Padding.symmetric(horizontal=12 if width < 380 else 16)
        chat_main.padding = ft.Padding.symmetric(
            horizontal=10 if width < 380 else 14,
            vertical=10 if height < 700 else 14,
        )
        image_preview_container.height = max(230, min(460, height * 0.44))
        page.update()

    def connectivity_changed(event) -> None:
        nonlocal is_offline
        is_offline = ft.ConnectivityType.NONE in (event.connectivity or [])
        offline_banner.visible = is_offline
        if is_offline and current_user is None:
            show_offline()
        elif not is_offline and root.content is offline_screen:
            page.run_task(bootstrap)
        else:
            page.update()

    def handle_unexpected_error(event) -> None:
        crash_protector.capture_flet_event(event)
        try:
            toast(MAINTENANCE_MESSAGE, error=True)
        except Exception as error:
            crash_protector.capture_exception(
                error, "Failed to display the unexpected-error notification"
            )

    connectivity.on_change = connectivity_changed
    page.on_login = complete_google_oauth
    page.on_resize = resize_layout
    page.on_error = handle_unexpected_error

    refresh_usage_ui()
    resize_layout()
    await bootstrap()
    if database_recovery_backup is not None:
        toast(
            "Local storage was repaired safely. A recovery backup was kept.",
            error=False,
        )
    elif database_recovery_mode:
        toast(
            "The app started in recovery mode. Earlier local history may be unavailable.",
            error=True,
        )


if __name__ == "__main__":
    ft.run(main, assets_dir="assets", port=8550)
