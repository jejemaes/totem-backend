import typing as t

from django.test import SimpleTestCase

from core.services.generics import check_concrete, generic_args_for, is_concrete

ModelT = t.TypeVar("ModelT")
CreateT = t.TypeVar("CreateT")
UpdateT = t.TypeVar("UpdateT")


class Base(t.Generic[ModelT]):
    pass


class CreateMix(t.Generic[CreateT]):
    pass


class UpdateMix(t.Generic[UpdateT]):
    pass


class Model:
    pass


class OtherModel:
    pass


class CreateInput:
    pass


class UpdateInput:
    pass


class TestGenericArgsFor(SimpleTestCase):
    def test_direct_parametrization(self):
        class Service(Base[Model]):
            pass

        self.assertEqual(generic_args_for(Service, Base), (Model,))

    def test_each_origin_picks_its_own_arguments(self):
        """The whole point of the split: one generic parameter per owner."""

        class Service(CreateMix[CreateInput], UpdateMix[UpdateInput], Base[Model]):
            pass

        self.assertEqual(generic_args_for(Service, CreateMix), (CreateInput,))
        self.assertEqual(generic_args_for(Service, UpdateMix), (UpdateInput,))
        self.assertEqual(generic_args_for(Service, Base), (Model,))

    def test_intermediate_inheritance_walks_the_mro(self):
        """A subclass that re-parametrizes nothing inherits the parametrization."""

        class Service(Base[Model]):
            pass

        class SubService(Service):
            pass

        self.assertEqual(generic_args_for(SubService, Base), (Model,))

    def test_subclass_reparametrization_wins(self):
        """The MRO is walked from `cls`, so the closest parametrization is found first."""

        class Service(Base[Model]):
            pass

        class SubService(Service, Base[OtherModel]):
            pass

        self.assertEqual(generic_args_for(SubService, Base), (OtherModel,))

    def test_absent_origin_returns_none(self):
        class Service(Base[Model]):
            pass

        self.assertIsNone(generic_args_for(Service, CreateMix))

    def test_unsubscripted_base_returns_none(self):
        """Inheriting without subscripting must not report the parent's arguments.

        This is why `__orig_bases__` is read from `__dict__` and not with `getattr`.
        """

        class Service(Base):
            pass

        self.assertIsNone(generic_args_for(Service, Base))


class TestIsConcrete(SimpleTestCase):
    def test_resolved_arguments(self):
        self.assertTrue(is_concrete((Model, CreateInput)))

    def test_typevar_is_not_concrete(self):
        self.assertFalse(is_concrete((ModelT,)))

    def test_forwardref_is_not_concrete(self):
        self.assertFalse(is_concrete((t.ForwardRef("Model"),)))


class TestCheckConcrete(SimpleTestCase):
    def test_concrete_arguments_pass(self):
        class Service(Base[Model]):
            pass

        self.assertTrue(check_concrete(Service, Base, (Model,)))

    def test_still_generic_class_reports_false_without_raising(self):
        """An abstract intermediate service has nothing to materialize yet."""

        class AbstractService(Base[ModelT]):
            pass

        self.assertEqual(AbstractService.__parameters__, (ModelT,))
        self.assertFalse(check_concrete(AbstractService, Base, (ModelT,)))

    def test_unresolved_argument_on_concrete_class_raises(self):
        class Service(Base[Model]):
            pass

        with self.assertRaises(TypeError) as ctx:
            check_concrete(Service, Base, (ModelT,))
        self.assertIn("does not fully parametrize", str(ctx.exception))
        self.assertIn("Base", str(ctx.exception))
