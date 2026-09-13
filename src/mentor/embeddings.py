from collections.abc import Sequence

from mentor.ports import ModelUnavailable

_NOT_BUILT = "The embedding model is not built yet; Videos can only be embedded once the model adapter lands"


class SentenceTransformerEmbedder:
    """Embedder backed by sentence-transformers. Unavailable until the adapter is built."""

    def __init__(self, model_name: str, dimension: int) -> None:
        self.model_name = model_name
        self.dimension = dimension

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        raise ModelUnavailable(_NOT_BUILT)

    def embed_query(self, text: str) -> list[float]:
        raise ModelUnavailable(_NOT_BUILT)
