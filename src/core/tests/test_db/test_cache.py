from django.core.cache import cache, caches
from django.test import SimpleTestCase

from core.db.tenancy import default_database, make_cache_key, use_database


class TenantCacheTestCase(SimpleTestCase):

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_key_namespaced_by_the_database(self):
        self.assertEqual(make_cache_key("key", "", 1), f":{default_database()}:1:key")
        with use_database("tenant_a"):
            self.assertEqual(make_cache_key("key", "totem", 2), "totem:tenant_a:2:key")

    def test_key_function_is_configured(self):
        for alias in caches:
            with self.subTest(alias=alias):
                self.assertIs(caches[alias].key_func, make_cache_key)

    def test_same_key_two_tenants(self):
        with use_database("tenant_a"):
            cache.set("menu", "menu of a")
        with use_database("tenant_b"):
            self.assertIsNone(cache.get("menu"))
            cache.set("menu", "menu of b")
        self.assertIsNone(cache.get("menu"))

        with use_database("tenant_a"):
            self.assertEqual(cache.get("menu"), "menu of a")
            cache.delete("menu")
        with use_database("tenant_b"):
            self.assertEqual(cache.get("menu"), "menu of b")

    def test_bulk_and_counter_operations(self):
        with use_database("tenant_a"):
            cache.set_many({"x": 1, "y": 2})
            cache.incr("x")
        with use_database("tenant_b"):
            self.assertEqual(cache.get_many(["x", "y"]), {})
        with use_database("tenant_a"):
            self.assertEqual(cache.get_many(["x", "y"]), {"x": 2, "y": 2})
