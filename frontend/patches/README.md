# three-stdlib 2.36.1

`OrbitControls` 原版将鼠标和触摸放进同一个触点列表，但只记录触摸坐标。鼠标拖动未结束时收到触摸移动，会进入双指缩放并读取不存在的坐标。

补丁在控件内部维护同一种输入的手势，忽略重复和未登记触点，使用指针捕获接收释放事件；取消、释放与销毁时同步清理状态。双指缩放结束后，剩余手指可以继续旋转。

ESM 和 CommonJS 入口采用相同修复，由 `pnpm-workspace.yaml` 和锁文件在安装时应用。保留 Drei 对相机、渲染更新和控件生命周期的管理。

升级依赖或移除补丁时运行：

```sh
python scripts/run_vitest.py run src/utils/__tests__/orbitPointerLifecycle.test.ts src/utils/__tests__/wheelZoom.test.ts
```

测试直接使用 Drei 所解析的真实依赖，覆盖混合输入、重复触点、外部触点、双指缩放、单指接续、取消和重连。
