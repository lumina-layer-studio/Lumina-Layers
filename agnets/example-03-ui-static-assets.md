# 示例 03：UI 组件外部资源

```html
<!-- ui/assets/template/new_modal.html -->
<div class="new-modal" id="{{modal_id}}">
    <div class="modal-header">
        <h3>{{title}}</h3>
        <button class="close-btn">&times;</button>
    </div>
    <div class="modal-content">
        {{content|safe}}
    </div>
</div>
```

```css
/* ui/static/css/new_modal.css - 通过文件路径引用 */
.new-modal {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
}
```

```python
# 通过 assets.py 加载模板
from ui.assets import load_template_text

def create_new_modal(title: str, content: str):
    template_str = load_template_text("new_modal.html")
    template = Template(template_str)
    return template.render(
        modal_id=f"modal_{uuid.uuid4().hex[:8]}",
        title=title,
        content=content,
    )

# CSS 在模板中通过文件路径引用：
# <link rel="stylesheet" href="/gradio_api/file=ui/static/css/new_modal.css">
```

```python
# 错误做法：硬编码 HTML/CSS
def create_new_modal(title, content):
    html = f"""
    <div class="new-modal">
        <div class="modal-header">
            <h3>{title}</h3>
            ...
        </div>
    </div>
    """
    return html
```
