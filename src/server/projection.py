from .models import EngineEvent


class ProjectionBuilder:
    def build(self, event: EngineEvent) -> list[EngineEvent]:
        projections = []
        if event.audience == "host":
            projections.append(event)
        elif event.audience == "player":
            projections.append(event)
        elif event.audience == "party":
            projections.append(event.model_copy(update={"audience": "host"}))
            projections.append(event.model_copy(update={"audience": "player"}))
        elif event.audience == "system":
            projections.append(event)
        return projections
