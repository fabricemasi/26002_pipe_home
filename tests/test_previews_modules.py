import _isolate  # noqa: F401 — les réglages réels restent isolés
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import previews
from preview_services import cache, images, memory, profiles

assert _isolate.REAL_DATA_UNTOUCHED


class PreviewModulesTest(unittest.TestCase):
    def test_profile_reload_updates_cache_signature_and_facade(self):
        source = Path('scene.blend')
        updated = {'LOW POLY': {'wireframe': False}}
        with patch.object(profiles, '_RENDER_PROFILES', {}), \
                patch.object(profiles, '_load_render_profiles', return_value=updated), \
                patch.object(profiles, '_write_profiles_snapshot') as save:
            before = cache._file_image_cache_signature(source)
            profiles._reload_render_profiles()
            self.assertNotEqual(before, cache._file_image_cache_signature(source))
            self.assertIs(previews._RENDER_PROFILES, updated)
            save.assert_called_once_with(updated)

    def test_lut_change_invalidates_shared_caches_and_misses(self):
        cube, photo = 'test.cube', 'photo.jpg'
        caches = (memory._file_image_cache, memory._file_image_high_cache,
                  memory._file_image_column_cache)
        with ExitStack() as stack:
            for target in caches:
                stack.enter_context(patch.dict(target, {cube: object(), photo: object()}, clear=True))
            for name in ('_PREVIEW_STALE_LOOKUP_MISSES', '_FILE_IMAGE_COLUMN_LOOKUP_MISSES'):
                stack.enter_context(patch.object(memory, name, {(cube, 1), (photo, 1)}))
            for name, value in [('LUT_TEST_IMAGES', []), ('LUT_DEFAULT_IMAGE', ''), ('LUT_IMAGE_CURVES', {})]:
                stack.enter_context(patch.object(images, name, value))
            images.set_lut_test_images(['test.png'], 'test.png')
            self.assertEqual(previews.LUT_DEFAULT_IMAGE, 'test.png')
            self.assertIs(previews.LUT_TEST_IMAGES, images.LUT_TEST_IMAGES)
            for target in caches:
                self.assertNotIn(cube, target)
                self.assertIn(photo, target)
            for name in ('_PREVIEW_STALE_LOOKUP_MISSES', '_FILE_IMAGE_COLUMN_LOOKUP_MISSES'):
                self.assertEqual(getattr(memory, name), {(photo, 1)})
