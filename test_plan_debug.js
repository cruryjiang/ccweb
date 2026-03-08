// 在浏览器控制台运行这个来调试 /plan 命令
console.log('=== /plan 命令调试信息 ===');
console.log('isGenerating:', window.isGenerating);
console.log('currentChatId:', window.currentChatId);
console.log('sessions:', Object.keys(window.sessions || {}));
console.log('sendBtn disabled:', document.getElementById('sendBtn')?.disabled);
console.log('userInput value:', document.getElementById('userInput')?.value);
