/* 简单的 Markdown 渲染（只处理关键元素） */
function renderMarkdown(text) {
    if (!text) return '';
    // 转义 HTML
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // 代码块 (```)
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // 行内代码 (`)
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 粗体 ** **
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // 表格 (简单处理)
    text = text.replace(/(\|[^\n]+\|\n\|[-| :]+\|\n(?:\|[^\n]+\|\n?)*)/g, function(match) {
        const lines = match.trim().split('\n');
        if (lines.length < 2) return match;
        let html = '<table><thead><tr>';
        const headers = lines[0].split('|').filter(c => c.trim());
        headers.forEach(h => { html += '<th>' + h.trim() + '</th>'; });
        html += '</tr></thead><tbody>';
        for (let i = 2; i < lines.length; i++) {
            const cells = lines[i].split('|').filter(c => c.trim());
            if (cells.length === 0) continue;
            html += '<tr>';
            cells.forEach(c => { html += '<td>' + c.trim() + '</td>'; });
            html += '</tr>';
        }
        html += '</tbody></table>';
        return html;
    });

    // 无序列表
    text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // 有序列表
    text = text.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');

    // 标题 (## 和 ###)
    text = text.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    text = text.replace(/^## (.+)$/gm, '<h3>$1</h3>');

    // 段落 (双换行分割)
    const paragraphs = text.split(/\n\n+/);
    if (paragraphs.length > 1) {
        text = paragraphs.map(function(p) {
            p = p.trim();
            if (!p) return '';
            if (p.startsWith('<')) return p;
            p = p.replace(/\n/g, '<br>');
            return '<p>' + p + '</p>';
        }).join('\n');
    } else {
        text = text.replace(/\n/g, '<br>');
    }

    return text;
}

/* ── Chat Application ────────────────────────── */
const chatApp = {
    sessionId: null,

    init: function() {
        this.cacheDOM();
        this.bindEvents();
        this.addWelcomeMessage();
    },

    cacheDOM: function() {
        this.messagesEl = document.getElementById('messages');
        this.loadingEl = document.getElementById('loading');
        this.inputBox = document.getElementById('input-box');
        this.sendBtn = document.getElementById('send-btn');
    },

    bindEvents: function() {
        var self = this;
        this.sendBtn.addEventListener('click', function() { self.send(); });
        this.inputBox.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                self.send();
            }
        });
    },

    addWelcomeMessage: function() {
        this.addMessage('assistant', '你好！我是多智能体数据查询助手。\n\n我可以帮你：\n- 查询 MySQL 数据库中的数据\n- 绘制数据图表\n\n请问有什么可以帮你的？');
    },

    addMessage: function(role, content) {
        var div = document.createElement('div');
        div.className = 'message ' + role;
        if (role === 'user') {
            div.innerHTML = '<p>' + content.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</p>';
        } else {
            div.innerHTML = renderMarkdown(content);
        }
        this.messagesEl.appendChild(div);
        this.scrollToBottom();
        return div;
    },

    scrollToBottom: function() {
        var container = document.getElementById('chat-container');
        container.scrollTop = container.scrollHeight;
    },

    send: async function() {
        var self = this;
        var text = this.inputBox.value.trim();
        if (!text) return;

        // 添加用户消息
        this.addMessage('user', text);
        this.inputBox.value = '';
        this.setLoading(true);

        // 预先创建空的 assistant 消息容器
        var assistantDiv = this.addMessage('assistant', '');
        var accumulated = '';

        try {
            var res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    session_id: this.sessionId,
                }),
            });

            if (!res.ok) {
                var errText = await res.text();
                throw new Error('请求失败 (' + res.status + '): ' + errText);
            }

            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            while (true) {
                var result = await reader.read();
                if (result.done) break;
                buffer += decoder.decode(result.value, { stream: true });

                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (line.startsWith('data: ')) {
                        var data = JSON.parse(line.slice(6));
                        if (data.token) {
                            accumulated += data.token;
                            assistantDiv.innerHTML = renderMarkdown(accumulated);
                            self.scrollToBottom();
                        }
                        if (data.done) {
                            self.sessionId = data.session_id;
                        }
                    }
                }
            }

            // 处理 buffer 中剩余的数据
            if (buffer.startsWith('data: ')) {
                var data = JSON.parse(buffer.slice(6));
                if (data.token) {
                    accumulated += data.token;
                    assistantDiv.innerHTML = renderMarkdown(accumulated);
                }
                if (data.done) {
                    self.sessionId = data.session_id;
                }
            }

        } catch (err) {
            assistantDiv.innerHTML = '<p>错误：' + err.message + '</p>';
        } finally {
            this.setLoading(false);
            this.inputBox.focus();
        }
    },

    setLoading: function(loading) {
        this.sendBtn.disabled = loading;
        this.loadingEl.classList.toggle('hidden', !loading);
    },
};

/* ── 启动 ────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() { chatApp.init(); });
