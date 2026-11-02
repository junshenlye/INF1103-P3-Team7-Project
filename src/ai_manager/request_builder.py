"""Construct provider messages without transport or domain policy."""

import base64
import mimetypes
from pathlib import Path
from ..ai_prompts import RELEVANCE_PROMPT, INTERPRETATION_PROMPT, NORMALIZATION_PROMPT


class RequestBuilder:
    def image_to_data_url(self, file_path):
        """Return an IO-validated image as a Base64 data URL for Qwen.

        File type, size and readability are not checked again here because those
        checks belong to IO Manager.
        """
        image_path = Path(file_path)
        (mime_type, _) = mimetypes.guess_type(image_path.name)
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded_image}"

    def create_image_messages(self, prompt, module_title, image_data, extra_text=None):
        """Build one multimodal message containing all module evidence images.

        The normalization pass also supplies the earlier interpretation memo.
        A string is accepted for backwards compatibility with existing callers.
        """
        text = f"{prompt}\n\nMODULE: {module_title}"
        if extra_text is not None:
            text += f"\n\nINTERPRETATION MEMO:\n{extra_text}"
        if isinstance(image_data, str):
            image_data = [image_data]
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    *[
                        {"type": "image_url", "image_url": {"url": image}}
                        for image in image_data
                    ],
                ],
            }
        ]

    def relevance(self, title, images):
        return self.create_image_messages(RELEVANCE_PROMPT, title, images)

    def interpretation(self, title, images):
        return self.create_image_messages(INTERPRETATION_PROMPT, title, images)

    def normalization(self, title, images, memo):
        return self.create_image_messages(NORMALIZATION_PROMPT, title, images, memo)
