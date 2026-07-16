import asyncio
import base64
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import IMAGE_MAX_RETRIES, IMAGE_REQUESTS_PER_MINUTE
from services.image_service import generate_flux_image_url


@dataclass
class ImageJob:
    prompt: str
    premium: bool
    future: asyncio.Future


class ImageGenerationQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[ImageJob] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None
        self.last_request_at = 0.0
        self.minimum_interval = 60.0 / max(1, IMAGE_REQUESTS_PER_MINUTE)

    @property
    def pending_count(self) -> int:
        return self.queue.qsize()

    async def generate(self, prompt: str, premium: bool = False) -> str:
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())
        future = asyncio.get_running_loop().create_future()
        await self.queue.put(ImageJob(prompt=prompt, premium=premium, future=future))
        return await future

    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                wait_for = self.minimum_interval - (time.monotonic() - self.last_request_at)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                result = await self._run_with_retries(job.prompt, job.premium)
                if not job.future.cancelled():
                    job.future.set_result(result)
            except Exception as error:
                if not job.future.cancelled():
                    job.future.set_exception(error)
            finally:
                self.last_request_at = time.monotonic()
                self.queue.task_done()

    async def _run_with_retries(self, prompt: str, premium: bool) -> str:
        last_error: Exception | None = None
        for attempt in range(IMAGE_MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._download_image, prompt, premium)
            except Exception as error:
                last_error = error
                if attempt + 1 < IMAGE_MAX_RETRIES:
                    await asyncio.sleep(3 * (attempt + 1))
        raise RuntimeError(f"Image generation failed after {IMAGE_MAX_RETRIES} attempts: {last_error}")

    @staticmethod
    def _download_image(prompt: str, premium: bool) -> str:
        url = generate_flux_image_url(prompt, premium)
        request = Request(url, headers={"User-Agent": "AI-Master-Pro/2.0"})
        try:
            with urlopen(request, timeout=90) as response:
                content_type = response.headers.get("Content-Type", "")
                image_bytes = response.read()
        except HTTPError as error:
            if error.code == 429:
                raise RuntimeError("The image provider is rate-limited. Your request will be retried.") from error
            raise RuntimeError(f"Image provider returned HTTP {error.code}.") from error
        except URLError as error:
            raise RuntimeError("Could not reach the image provider.") from error

        if not content_type.startswith("image/") or len(image_bytes) < 1_000:
            raise RuntimeError("The image provider returned an invalid response.")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        mime = content_type.split(";", 1)[0]
        return f"data:{mime};base64,{encoded}"
