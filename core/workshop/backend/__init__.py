"""Host-managed Creative Workshop module backends.

Submodules are imported directly (``core.workshop.backend.runtime`` and so
on) so that the package validator can use the lock parser without importing
the process runtime.
宿主托管的创意工坊模块后端。各子模块按需直接导入，避免包检查器加载进程运行时。
"""
