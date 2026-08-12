"""请求线程 join 回波移动时，必须问预算，而不是用自己的常数。

这条测试守的是两侧，缺一侧它就成了装饰：
  · 有预算时**真的等**——否则冷天的第一个读者永远看不到移动（他付钱预热，
    下一个读者收货）。
  · 没预算时**一秒都不等**——原来的 bug 不是"等待"，是那个 join 从不查 deadline，
    1.2s 取帧 + 3.0s 等移动，走穿了当时 3 秒的墙。
"""
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))   # 后插的赢：仓库根有一份化石

import net_budget                       # noqa: E402
import render_scene as RS               # noqa: E402


class MotionJoinBudgeted(unittest.TestCase):
    # 每个用例一把自己的钥匙。**移动答案落在共享磁盘上**(_mo_put 写盘)，
    # 只清内存字典清不掉它——第一版就是这么把一个用例的结果漏给了下一个。
    _n = [0]

    def setUp(self):
        MotionJoinBudgeted._n[0] += 1
        self.key = (10.0 + MotionJoinBudgeted._n[0], 20.0 + MotionJoinBudgeted._n[0])
        RS._MO_CACHE.pop(self.key, None)

    def _thread_that_answers_after(self, delay):
        def run():
            time.sleep(delay)
            RS._mo_put(self.key, {"kind": "moving", "kmh": 30})
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return (self.key, t)

    def test_waits_when_the_budget_allows(self):
        h = self._thread_that_answers_after(0.3)
        with net_budget.request_budget(5.0):
            t0 = time.time()
            mo = RS._motion_join_budgeted(h)
            waited = time.time() - t0
        self.assertEqual(mo.get("kind"), "moving",
                         "预算充足却没等到——冷天第一个读者又看不到移动了")
        self.assertGreater(waited, 0.2, "它根本没等")

    def test_does_not_wait_past_the_deadline(self):
        h = self._thread_that_answers_after(3.0)
        with net_budget.request_budget(0.30):     # 比 RESERVE 大不了多少
            t0 = time.time()
            mo = RS._motion_join_budgeted(h)
            waited = time.time() - t0
        self.assertIsNone(mo.get("kind"), "预算耗尽时不该拿到答案")
        self.assertLess(waited, 0.5,
                        "它无视了 deadline —— 这正是当年走穿 3 秒墙的那个 bug")

    def test_cap_bounds_a_generous_deadline(self):
        h = self._thread_that_answers_after(30.0)
        with net_budget.request_budget(60.0):
            t0 = time.time()
            RS._motion_join_budgeted(h, cap=0.2)
            waited = time.time() - t0
        self.assertLess(waited, 1.0, "上限没生效，一个慷慨的 deadline 就能吊住请求")


if __name__ == "__main__":
    unittest.main()
