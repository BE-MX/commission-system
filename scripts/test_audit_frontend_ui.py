"""Negative examples for the UI gate; no browser or production service required."""
import unittest
from audit_frontend_ui import _vue_metrics, _js_metrics, _tags, apply_exceptions, baseline_increases, STICKY_SCROLLBAR


class UiGateTests(unittest.TestCase):
    def test_pagination_layout_sizes_and_default(self):
        good = '<el-pagination layout="total, sizes, prev, pager, next" :page-sizes="[20, 50, 100]" />'
        self.assertEqual(_vue_metrics(good)['bad_pagination_sizes'], 0)
        for bad in (good.replace('100', '200'), good.replace(':page-sizes="[20, 50, 100]"', ''), good.replace('[20, 50, 100]', '[50, 100]')):
            self.assertEqual(_vue_metrics(bad)['bad_pagination_sizes'], 1)
        self.assertEqual(_vue_metrics(good.replace('total, sizes, prev, pager, next', 'prev, pager, next'))['bad_pagination_layout'], 1)
        self.assertEqual(_js_metrics('useListPage(fetch, { pageSize: 50 })')['bad_page_default'], 1)
        self.assertEqual(_js_metrics('const pageSize = ref(100)')['bad_page_default'], 1)
        self.assertEqual(_js_metrics('const pageSize = ref(20); useListPage(fetch, { pageSize: 20 })')['bad_page_default'], 0)

    def test_form_labels_and_glass_button_sizes(self):
        self.assertEqual(_vue_metrics('<el-form label-position="top" />')['form_label_position'], 0)
        for tag in ('<el-form />', '<el-form label-position="right" />'):
            self.assertEqual(_vue_metrics(tag)['form_label_position'], 1)
        self.assertEqual(_vue_metrics('<GlassButton />')['non_md_glass_button'], 0)
        self.assertEqual(_vue_metrics('<GlassButton size="sm" />')['non_md_glass_button'], 1)
        self.assertEqual(_vue_metrics('<GlassButton size="small" />')['bad_glass_button_size'], 1)

    def test_shared_feedback_and_validator_implementations_are_scoped(self):
        source = r'ElMessage.error("failed"); const phone = /^1[3-9]\d{9}$/'
        metrics = _js_metrics(source)
        self.assertGreater(metrics['message_calls'], 0)
        self.assertEqual(metrics['inline_public_validator'], 1)
        self.assertGreater(apply_exceptions('frontend/src/views/a.js', metrics, {})['message_calls'], 0)
        self.assertEqual(apply_exceptions('frontend/src/utils/feedback.js', metrics, {})['message_calls'], 0)
        self.assertEqual(apply_exceptions('frontend/src/utils/validators.js', metrics, {})['inline_public_validator'], 0)

    def test_compact_exception_is_capped_and_new_debt_cannot_raise_baseline(self):
        exceptions = {'a.vue': {'non_md_glass_button': {'count': 1, 'reason': 'card action'}}}
        self.assertEqual(apply_exceptions('a.vue', {'non_md_glass_button': 2}, exceptions)['non_md_glass_button'], 1)
        self.assertEqual(apply_exceptions('b.vue', {'non_md_glass_button': 1}, exceptions)['non_md_glass_button'], 1)
        self.assertTrue(baseline_increases({'a.vue': {'small_controls': 2}}, {'a.vue': {'small_controls': 1}}))
        self.assertFalse(baseline_increases({'a.vue': {'small_controls': 0}}, {'a.vue': {'small_controls': 1}}))

    def test_tag_parser_preserves_quoted_comparisons_and_distinguishes_columns(self):
        self.assertEqual(len(_tags('<el-table v-if="rows.length > 0"><el-table-column /></el-table>', 'el-table')), 1)

    def test_sticky_scrollbar_directive_detection(self):
        good = '<el-table :data="rows" border class="list-table" v-sticky-scrollbar>'
        self.assertIsNotNone(STICKY_SCROLLBAR.search(good))
        # 显式关闭是刻意的评审豁口，存在即视为已声明
        self.assertIsNotNone(STICKY_SCROLLBAR.search('<el-table v-sticky-scrollbar="false">'))
        for tag in ('<el-table :data="rows" border class="list-table">', '<el-table>'):
            self.assertIsNone(STICKY_SCROLLBAR.search(tag))
        # el-table-column 不能冒充表格声明
        self.assertIsNone(STICKY_SCROLLBAR.search('<el-table-column prop="name" />'))


if __name__ == '__main__':
    unittest.main()
