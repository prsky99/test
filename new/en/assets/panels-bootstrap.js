/* Restore inactive panels before the shared operating handlers attach. */
(() => { for (const node of document.querySelectorAll('template[data-inactive-panel]')) node.replaceWith(node.content); })();
