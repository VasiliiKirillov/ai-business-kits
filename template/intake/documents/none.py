class NoDocuments:
    def render(self, booking: dict) -> dict:
        return {"url": None, "path": None, "id": None}

    def delete(self, result: dict) -> None:
        pass
