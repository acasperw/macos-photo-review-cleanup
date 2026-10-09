import numpy as np
import open_clip
import torch
from PIL import Image

MODEL_NAME = "ViT-B-16"
PRETRAINED = "datacomp_xl_s13b_b90k"
MODEL_ID = f"{MODEL_NAME}/{PRETRAINED}"


class Clip:
    def __init__(self) -> None:
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=PRETRAINED, device=self.device
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(MODEL_NAME)

    @torch.no_grad()
    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        batch = torch.stack([self.preprocess(img) for img in images]).to(self.device)
        return self._normalise(self.model.encode_image(batch))

    @torch.no_grad()
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        tokens = self.tokenizer(texts).to(self.device)
        return self._normalise(self.model.encode_text(tokens))

    @staticmethod
    def _normalise(features: torch.Tensor) -> np.ndarray:
        features = features / features.norm(dim=-1, keepdim=True)
        return features.float().cpu().numpy()
