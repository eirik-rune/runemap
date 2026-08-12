"""请求线程 join 回波移动时，必须问预算，而不是用自己的常数。

这条测试守的是两侧，缺一侧它就成了装饰：
  · 有预算时**真的等**——否则冷天的第一个读者永远看不到移动（他付钱预热，
    下一个读者收货）。
  · 没预算时**一秒都不等**——原来的 bug 不是"等待"，是那个 join 从不查 deadline，
    1.2s 取帧 + 3.0s 等移动，走穿了当时 3 秒的墙。
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))   # 后插的赢：仓库根有一份化石

import net_budget                       # noqa: E402
import render_scene as RS               # noqa: E402


class MotionJoinBudgeted(unittest.TestCase):
    # **移动答案的权威在磁盘上**(_mo_get: "The disk entry is the authority")。
    # 第一版只清内存字典 -> 同一次运行里互相污染；第二版给每格换钥匙 ->
    # 键是确定性的，**上一次运行留在盘上的条目这一次照样读得到**。
    # 真隔离只有一种：把 _MO_DIR 指到一个临时目录，并逐格删文件。
    _n = [0]

    def setUp(self):
        MotionJoinBudgeted._n[0] += 1
        self.key = (10.0 + MotionJoinBudgeted._n[0], 20.0 + MotionJoinBudgeted._n[0])
        self._tmp = tempfile.mkdtemp(prefix="mo_test_")
        self._saved_dir = RS._MO_DIR
        RS._MO_DIR = self._tmp
        RS._MO_CACHE.pop(self.key, None)
        self.assertIsNone(RS._mo_get(self.key), "起点必须是空的，否则这格测的是上一格")

    def tearDown(self):
        RS._MO_DIR = self._saved_dir
        RS._MO_CACHE.pop(self.key, None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _thread_that_answers_after(self, delay):
        """句柄里装的是 Event，不是 Thread —— 因为等的人不一定是起的人。"""
        ev = threading.Event()

        def run():
            time.sleep(delay)
            RS._mo_put(self.key, {"kind": "moving", "kmh": 30})
            ev.set()
        threading.Thread(target=run, daemon=True).start()
        return (self.key, ev)

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


class SomeoneElseIsComputing(unittest.TestCase):
    """后台预热几乎总是先到，读者随后才来。

    旧的 _motion_start 在这种情况下返回 (key, None) —— 「已经有人在算」和
    「不用等」被压成了同一个答案，于是**读者永远等不到任何东西**，而请求路径
    加不加 join 都一样。这一格就是那个 bug。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mo_test2_")
        self._saved = RS._MO_DIR
        RS._MO_DIR = self._tmp
        self.key = (33.3, 44.4)
        RS._MO_CACHE.pop(self.key, None)
        RS._MO_BUSY.discard(self.key)
        RS._MO_INFLIGHT.pop(self.key, None)

    def tearDown(self):
        RS._MO_DIR = self._saved
        RS._MO_CACHE.pop(self.key, None)
        RS._MO_BUSY.discard(self.key)
        RS._MO_INFLIGHT.pop(self.key, None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_second_caller_gets_a_waitable_handle(self):
        ev = threading.Event()
        RS._MO_INFLIGHT[self.key] = ev          # 假装后台预热正在算
        RS._MO_BUSY.add(self.key)

        key, handle = RS._motion_start([], 44.4, 33.3)
        self.assertIs(handle, ev,
                      "第二个调用者拿不到可等待的句柄 —— 读者又会白等")

        def finish():
            time.sleep(0.2)
            RS._mo_put(self.key, {"kind": "moving", "kmh": 42})
            RS._MO_INFLIGHT.pop(self.key, None)
            ev.set()
        threading.Thread(target=finish, daemon=True).start()

        with net_budget.request_budget(5.0):
            mo = RS._motion_join_budgeted((key, handle))
        self.assertEqual(mo.get("kind"), "moving",
                         "等到了却没读到结果")


if __name__ == "__main__":
    unittest.main()
