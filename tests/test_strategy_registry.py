"""Registry-level invariants: every registered strategy must be plug-in ready.

Adding a strategy in the wrong way (missing handler module, missing fields,
broken Pydantic defaults) trips one of these tests before it can ship.
"""
import importlib

import pytest

from web.schemas.strategy_params import STRATEGY_REGISTRY, field_specs


@pytest.mark.parametrize("strategy_name", list(STRATEGY_REGISTRY))
class TestEachStrategyIsValid:
    def test_descriptor_has_required_attributes(self, strategy_name):
        d = STRATEGY_REGISTRY[strategy_name]
        assert d.params_model is not None
        assert d.basic_fields and isinstance(d.basic_fields, tuple)
        assert d.advanced_fields and isinstance(d.advanced_fields, tuple)
        assert d.tf_high and d.tf_low
        assert d.label
        assert d.handler_module

    def test_params_model_default_instance(self, strategy_name):
        """A fresh ``ParamsModel()`` (all defaults) must validate cleanly."""
        d = STRATEGY_REGISTRY[strategy_name]
        instance = d.params_model()
        dumped = instance.model_dump()
        assert isinstance(dumped, dict) and dumped  # non-empty

    def test_field_groups_reference_real_fields(self, strategy_name):
        d = STRATEGY_REGISTRY[strategy_name]
        all_fields = set(d.params_model.model_fields.keys())
        declared = set(d.basic_fields) | set(d.advanced_fields)
        # Every grouped field must exist on the model (typos in registry fail here).
        unknown = declared - all_fields
        assert not unknown, f"{strategy_name}: unknown fields in basic/advanced: {unknown}"

    def test_field_specs_renders_without_error(self, strategy_name):
        d = STRATEGY_REGISTRY[strategy_name]
        specs = field_specs(d.params_model)
        for fname in d.basic_fields + d.advanced_fields:
            assert fname in specs

    def test_handler_module_exports_required_functions(self, strategy_name):
        d = STRATEGY_REGISTRY[strategy_name]
        module = importlib.import_module(d.handler_module)
        for fn in ("build", "scan", "format_alert"):
            assert callable(getattr(module, fn, None)), \
                f"{d.handler_module} missing callable '{fn}'"

    def test_handler_build_returns_two_strategies(self, strategy_name):
        """Builder must accept the model's default params and return a pair."""
        d = STRATEGY_REGISTRY[strategy_name]
        module = importlib.import_module(d.handler_module)
        defaults = d.params_model().model_dump()
        result = module.build(defaults)
        assert isinstance(result, tuple) and len(result) == 2
