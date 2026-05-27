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
    hitlPending: false,
    currentAssistantDiv: null,
    accumulated: '',

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

    /* ── SSE 流式读取 ───────────────────────── */

    readSSEStream: async function(response, onToken, onDone, onHitl) {
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var result = await reader.read();
            if (result.done) {
                console.log('[SSE] 流结束');
                if (buffer.trim() && buffer.trim().startsWith('data: ')) {
                    var trimmed = buffer.trim();
                    try {
                        var lastData = JSON.parse(trimmed.slice(6));
                        if (lastData.type === 'hitl_required') {
                            onHitl(lastData.session_id, lastData.query, lastData.result);
                        } else if (lastData.token) {
                            onToken(lastData.token);
                        } else if (lastData.done) {
                            onDone(lastData.session_id);
                        }
                    } catch (e) {
                        console.error('[SSE] 残留buffer解析失败:', e.message);
                    }
                }
                break;
            }
            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line.startsWith('data: ')) continue;
                try {
                    var data = JSON.parse(line.slice(6));
                    console.log('[SSE] 收到事件:', data.type || (data.token ? 'token' : (data.done ? 'done' : 'other')));

                    if (data.type === 'hitl_required') {
                        onHitl(data.session_id, data.query, data.result);
                    } else if (data.token) {
                        onToken(data.token);
                    } else if (data.done) {
                        onDone(data.session_id);
                    }
                } catch (e) {
                    console.error('[SSE] JSON解析失败:', e.message, 'line:', line.slice(0, 100));
                }
            }
        }
    },

    /* ── 发送消息 ────────────────────────────── */

    send: async function() {
        var self = this;
        var text = this.inputBox.value.trim();
        if (!text || this.hitlPending) return;

        this.addMessage('user', text);
        this.inputBox.value = '';
        this.setLoading(true);

        this.accumulated = '';
        this.hitlProcessed = false;
        this.currentAssistantDiv = this.addMessage('assistant', '');

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

            await this.readSSEStream(
                res,
                function(token) {
                    if (self.hitlProcessed) return;
                    self.accumulated += token;
                    self.currentAssistantDiv.innerHTML = renderMarkdown(self.accumulated);
                    self.scrollToBottom();
                },
                function(sid) {
                    self.sessionId = sid;
                },
                function(sid, query, result) {
                    console.log('[HITL] onHitl 回调被调用, session_id:', sid, 'query:', (query || '').slice(0, 80));
                    self.sessionId = sid;
                    self.hitlProcessed = true;
                    self.currentAssistantDiv.innerHTML = '<p style="color:#667eea;font-weight:bold">查询已执行，等待审核...</p>';
                    self.createFeedbackUI(sid, query, result);
                }
            );

        } catch (err) {
            this.currentAssistantDiv.innerHTML = '<p>错误：' + err.message + '</p>';
        } finally {
            if (!this.hitlPending) {
                this.setLoading(false);
            }
            this.inputBox.focus();
        }
    },

    /* ── HITL 反馈 UI ────────────────────────── */

    createFeedbackUI: function(sessionId, query, result) {
        var self = this;
        this.hitlPending = true;
        this.setLoading(false);

        var queryBlock = query
            ? '<div class="hitl-sql"><strong>执行SQL：</strong><pre><code>' +
              query.replace(/</g, '&lt;').replace(/>/g, '&gt;') +
              '</code></pre></div>'
            : '';
        var resultBlock = result
            ? '<div class="hitl-result"><strong>查询结果：</strong><pre><code>' +
              result.replace(/</g, '&lt;').replace(/>/g, '&gt;') +
              '</code></pre></div>'
            : '';

        var fbDiv = document.createElement('div');
        fbDiv.className = 'hitl-feedback';
        fbDiv.id = 'hitl-' + sessionId;
        fbDiv.innerHTML =
            queryBlock +
            resultBlock +
            '<div class="hitl-label">请审核查询结果：</div>' +
            '<div class="hitl-buttons">' +
            '  <button class="hitl-btn hitl-approve" data-decision="准确">准确</button>' +
            '  <button class="hitl-btn hitl-reject" data-decision="错误">错误</button>' +
            '  <button class="hitl-btn hitl-suggest" data-decision="其他建议">其他建议</button>' +
            '</div>' +
            '<div class="hitl-extra hidden">' +
            '  <textarea class="hitl-extra-input" placeholder="请描述具体问题或建议..."></textarea>' +
            '</div>';

        this.messagesEl.appendChild(fbDiv);
        this.scrollToBottom();

        // 绑定按钮事件
        var buttons = fbDiv.querySelectorAll('.hitl-btn');
        var extraDiv = fbDiv.querySelector('.hitl-extra');
        var extraInput = fbDiv.querySelector('.hitl-extra-input');

        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var decision = btn.getAttribute('data-decision');
                if (decision === '错误' || decision === '其他建议') {
                    // 展开文本框
                    if (extraDiv.classList.contains('hidden')) {
                        extraDiv.classList.remove('hidden');
                        extraInput.focus();
                        return; // 等待用户输入后再提交
                    }
                    // 已展开，获取输入内容提交
                    var msg = extraInput.value.trim();
                    self.submitFeedback(sessionId, decision, msg, fbDiv);
                } else {
                    self.submitFeedback(sessionId, decision, '', fbDiv);
                }
            });
        });
    },

    submitFeedback: async function(sessionId, decision, message, fbDiv) {
        var self = this;

        // 移除反馈 UI
        fbDiv.remove();
        this.hitlPending = false;
        this.setLoading(true);

        // 创建新的 assistant 消息容器接收后续输出
        this.accumulated = '';
        this.hitlProcessed = false;
        this.currentAssistantDiv = this.addMessage('assistant', '');

        try {
            var res = await fetch('/api/chat/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    decision: decision,
                    message: message,
                }),
            });

            if (!res.ok) {
                var errText = await res.text();
                throw new Error('反馈提交失败 (' + res.status + '): ' + errText);
            }

            await this.readSSEStream(
                res,
                function(token) {
                    if (self.hitlProcessed) return;
                    self.accumulated += token;
                    self.currentAssistantDiv.innerHTML = renderMarkdown(self.accumulated);
                    self.scrollToBottom();
                },
                function() {},
                function(sid, query, result) {
                    console.log('[HITL] submitFeedback 中收到二次审核, session_id:', sid);
                    self.sessionId = sid;
                    self.hitlProcessed = true;
                    self.currentAssistantDiv.innerHTML = '<p style="color:#667eea;font-weight:bold">查询已执行，等待审核...</p>';
                    self.createFeedbackUI(sid, query, result);
                }
            );

        } catch (err) {
            this.currentAssistantDiv.innerHTML = '<p>错误：' + err.message + '</p>';
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
