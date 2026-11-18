"""get_engine(): выбор движка документов по config.documents.engine."""
from ..config import Config


def get_engine(cfg: Config):
    e = cfg.documents.engine
    if e == "docx":
        from .docx import DocxEngine
        return DocxEngine(cfg)
    if e == "google_docs":
        from .google_docs import GoogleDocsEngine
        return GoogleDocsEngine(cfg)
    from .none import NoDocuments
    return NoDocuments()
