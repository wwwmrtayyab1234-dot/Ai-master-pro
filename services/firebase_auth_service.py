import json
import os
import re
import threading
import webbrowser
from dataclasses import dataclass
from email.utils import parseaddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OFFLINE_MESSAGE = "Please turn on your internet connection to continue your chat."
MAINTENANCE_MESSAGE = (
    "Dear User, the app is currently under maintenance. Please try again later."
)


class EmailVerificationRequired(RuntimeError):
    pass


class SessionExpired(RuntimeError):
    pass


@dataclass(frozen=True)
class FirebaseUser:
    uid: str
    email: str
    id_token: str
    refresh_token: str = ""
    email_verified: bool = False


class FirebaseAuthService:
    BASE_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
    TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
    TEMP_EMAIL_DOMAINS = {
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "temp-mail.org",
        "tempmail.com",
        "yopmail.com",
    }

    @property
    def configured(self) -> bool:
        return bool(os.getenv("FIREBASE_API_KEY"))

    @staticmethod
    def validate_email(email: str) -> str:
        clean = email.strip().lower()
        parsed = parseaddr(clean)[1]
        if (
            parsed != clean
            or len(clean) > 254
            or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", clean)
        ):
            raise ValueError("Enter a valid email address.")
        domain = clean.rsplit("@", 1)[1]
        if domain in FirebaseAuthService.TEMP_EMAIL_DOMAINS:
            raise ValueError("Temporary email addresses are not supported.")
        return clean

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")
        if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            raise ValueError("Password must contain at least one letter and one number.")

    @staticmethod
    def _friendly_http_error(error: HTTPError) -> RuntimeError:
        try:
            details = json.loads(error.read().decode("utf-8"))
            code = str(details.get("error", {}).get("message", ""))
        except Exception:
            code = ""
        messages = {
            "EMAIL_EXISTS": "An account already exists for this email.",
            "EMAIL_NOT_FOUND": "No account was found for this email.",
            "INVALID_PASSWORD": "The email or password is incorrect.",
            "INVALID_LOGIN_CREDENTIALS": "The email or password is incorrect.",
            "USER_DISABLED": "This account has been disabled.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please try again later.",
            "INVALID_REFRESH_TOKEN": "Your saved session has expired.",
            "TOKEN_EXPIRED": "Your saved session has expired.",
            "USER_NOT_FOUND": "Your saved session is no longer valid.",
        }
        if code in {"INVALID_REFRESH_TOKEN", "TOKEN_EXPIRED", "USER_NOT_FOUND"}:
            return SessionExpired(messages[code])
        return RuntimeError(messages.get(code, MAINTENANCE_MESSAGE))

    def _post(
        self,
        endpoint: str,
        payload: dict,
        timeout: int = 25,
        headers: dict[str, str] | None = None,
    ) -> dict:
        api_key = os.getenv("FIREBASE_API_KEY")
        if not api_key:
            raise RuntimeError("Firebase is not configured. Add FIREBASE_API_KEY to .env.")
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        request = Request(
            f"{self.BASE_URL}:{endpoint}?key={api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise self._friendly_http_error(error) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(OFFLINE_MESSAGE) from error

    def _lookup(self, id_token: str) -> dict:
        response = self._post("lookup", {"idToken": id_token})
        users = response.get("users") or []
        if not users:
            raise SessionExpired("Your account session is no longer valid.")
        return users[0]

    def _user(self, response: dict, require_verified: bool = True) -> FirebaseUser:
        account = self._lookup(response["idToken"])
        verified = bool(account.get("emailVerified", False))
        if require_verified and not verified:
            raise EmailVerificationRequired(
                "Verify your email using the link we sent, then sign in again."
            )
        return FirebaseUser(
            uid=response.get("localId") or account["localId"],
            email=response.get("email") or account.get("email", ""),
            id_token=response["idToken"],
            refresh_token=response.get("refreshToken", ""),
            email_verified=verified,
        )

    def sign_up(self, email: str, password: str) -> FirebaseUser:
        clean_email = self.validate_email(email)
        self.validate_password(password)
        response = self._post(
            "signUp",
            {"email": clean_email, "password": password, "returnSecureToken": True},
        )
        user = self._user(response, require_verified=False)
        self.send_email_verification(user.id_token)
        return user

    def sign_in(self, email: str, password: str) -> FirebaseUser:
        clean_email = self.validate_email(email)
        response = self._post(
            "signInWithPassword",
            {"email": clean_email, "password": password, "returnSecureToken": True},
        )
        return self._user(response, require_verified=True)

    def send_email_verification(self, id_token: str) -> None:
        self._post("sendOobCode", {"requestType": "VERIFY_EMAIL", "idToken": id_token})

    def send_password_reset(self, email: str) -> str:
        """Request an English Firebase reset email and confirm its recipient."""
        clean_email = self.validate_email(email)
        response = self._post(
            "sendOobCode",
            {"requestType": "PASSWORD_RESET", "email": clean_email},
            headers={"X-Firebase-Locale": "en"},
        )
        returned_email = str(response.get("email", clean_email)).strip().lower()
        if returned_email != clean_email:
            raise RuntimeError(MAINTENANCE_MESSAGE)
        return clean_email

    def refresh_session(self, refresh_token: str, email_hint: str = "") -> FirebaseUser:
        api_key = os.getenv("FIREBASE_API_KEY")
        if not api_key:
            raise RuntimeError("Firebase is not configured. Add FIREBASE_API_KEY to .env.")
        request = Request(
            f"{self.TOKEN_URL}?key={api_key}",
            data=urlencode(
                {"grant_type": "refresh_token", "refresh_token": refresh_token}
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=25) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise self._friendly_http_error(error) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(OFFLINE_MESSAGE) from error
        normalized = {
            "localId": data["user_id"],
            "email": email_hint,
            "idToken": data["id_token"],
            "refreshToken": data.get("refresh_token", refresh_token),
        }
        return self._user(normalized, require_verified=True)

    def delete_account(self, id_token: str) -> None:
        self._post("delete", {"idToken": id_token})

    def sign_in_with_google_access_token(
        self,
        access_token: str,
        request_uri: str,
    ) -> FirebaseUser:
        """Exchange an official Google OAuth token for a Firebase session."""
        if not access_token.strip() or not request_uri.strip():
            raise ValueError("The Google sign-in response is incomplete.")
        response = self._post(
            "signInWithIdp",
            {
                "postBody": urlencode(
                    {
                        "access_token": access_token,
                        "providerId": "google.com",
                    }
                ),
                "requestUri": request_uri,
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
        )
        return self._user(response, require_verified=True)

    def sign_in_with_google(self) -> FirebaseUser:
        config = {
            "apiKey": os.getenv("FIREBASE_API_KEY"),
            "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
            "projectId": os.getenv("FIREBASE_PROJECT_ID"),
            "appId": os.getenv("FIREBASE_APP_ID"),
        }
        missing = [name for name, value in config.items() if not value]
        if missing:
            raise RuntimeError(f"Firebase .env values missing: {', '.join(missing)}")

        completed = threading.Event()
        result: dict = {}
        page_template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AI Master Pro - Google Sign-In</title>
<style>body{font-family:Arial,sans-serif;background:#f5f7fb;color:#14213d;display:grid;place-items:center;height:100vh;margin:0}.box{background:white;padding:32px;border-radius:24px;border:1px solid #e2e8f0;max-width:380px;text-align:center;box-shadow:0 20px 60px #1d4ed822}button{background:#5b8def;color:#fff;border:0;border-radius:14px;padding:14px 22px;font-size:16px;font-weight:700;cursor:pointer}#status{margin-top:14px;color:#64748b}</style>
</head><body><div class="box"><h2>AI Master Pro</h2><p>Continue securely with your Google account.</p><button id="login">Continue with Google</button><div id="status"></div></div>
<script type="module">
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
const app = initializeApp(__FIREBASE_CONFIG__); const auth = getAuth(app);
document.getElementById("login").onclick = async () => { const status=document.getElementById("status"); status.textContent="Opening Google..."; try { const credential=await signInWithPopup(auth,new GoogleAuthProvider()); const payload={uid:credential.user.uid,email:credential.user.email||"",idToken:await credential.user.getIdToken(),refreshToken:credential.user.refreshToken||""}; await fetch("/token",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); status.textContent="Sign-in complete. You can close this window."; } catch(error){status.textContent=error.message;} };
</script></body></html>"""
        page_bytes = page_template.replace(
            "__FIREBASE_CONFIG__", json.dumps(config)
        ).encode("utf-8")

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args) -> None:
                return

            def do_GET(self) -> None:
                if self.path != "/":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page_bytes)))
                self.end_headers()
                self.wfile.write(page_bytes)

            def do_POST(self) -> None:
                if self.path != "/token":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not payload.get("uid") or not payload.get("idToken"):
                        raise ValueError("Invalid Google sign-in response")
                    result.update(payload)
                    self.send_response(204)
                    self.end_headers()
                    completed.set()
                except Exception as error:
                    result["error"] = str(error)
                    self.send_error(400)
                    completed.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        webbrowser.open(f"http://localhost:{server.server_port}/")
        finished = completed.wait(timeout=180)
        server.shutdown()
        server.server_close()
        if not finished:
            raise RuntimeError("Google sign-in timed out. Please try again.")
        if result.get("error"):
            raise RuntimeError(result["error"])
        account = self._lookup(result["idToken"])
        return FirebaseUser(
            uid=result["uid"],
            email=result.get("email", ""),
            id_token=result["idToken"],
            refresh_token=result.get("refreshToken", ""),
            email_verified=bool(account.get("emailVerified", True)),
        )
