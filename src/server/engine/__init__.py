"""Engine package public exports, loaded lazily to avoid module import cycles."""

from importlib import import_module


_EXPORTS = {
    "Engine": (".engine", "Engine"),
    "ResolutionPipeline": (".resolution_pipeline", "ResolutionPipeline"),
    "ProjectionDispatcher": (".projection", "ProjectionDispatcher"),
    "ProjectionBuilder": (".projection", "ProjectionBuilder"),
    "BatchCollector": (".batch", "BatchCollector"),
    "roll_skill_check": (".skill_check", "roll_skill_check"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
