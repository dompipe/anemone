(() => {
  'use strict';
  const prompt = document.getElementById('prompt');
  const newChat = document.getElementById('newChat');
  const conversation = document.getElementById('conversation');
  if (!prompt || !newChat || !conversation) return;

  const forcePrompt = () => {
    if (prompt.placeholder !== 'Ask anything… taxonomy selection is optional.') {
      prompt.placeholder = 'Ask anything… taxonomy selection is optional.';
    }
  };
  forcePrompt();
  new MutationObserver(forcePrompt).observe(prompt, {attributes:true, attributeFilter:['placeholder']});

  newChat.addEventListener('click', () => {
    queueMicrotask(() => {
      conversation.innerHTML = `
        <div class="welcome" id="welcome">
          <h1>Ask anything.<br>Taxonomy is optional context.</h1>
          <p>Start with an ordinary question. Anemone will resolve knowledge first and attach taxonomy only when it is relevant.</p>
          <div class="suggestions">
            <button class="suggestion" data-general-prompt="What is a bird?"><b>Ask normally</b><span>No kingdom or corpus selection required.</span></button>
            <button class="suggestion" data-general-prompt="What is gravity?"><b>Cross-domain knowledge</b><span>Use the general corpus before taxonomy.</span></button>
            <button class="suggestion" data-general-prompt="Tell me about Canis lupus and show the traits it inherits."><b>Taxonomy when useful</b><span>Lineage appears automatically.</span></button>
          </div>
        </div>`;
      conversation.querySelectorAll('[data-general-prompt]').forEach((button) => {
        button.addEventListener('click', () => {
          prompt.value = button.dataset.generalPrompt || '';
          prompt.focus();
          prompt.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
        });
      });
    });
  });
})();
