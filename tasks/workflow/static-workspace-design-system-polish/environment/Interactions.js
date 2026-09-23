const filter = document.querySelector('#filter');
if (filter) filter.addEventListener('change', () => {
  for (const row of document.querySelectorAll('tbody tr')) row.hidden = filter.value !== 'all' && row.dataset.state !== filter.value;
});
const form = document.querySelector('form');
if (form) form.addEventListener('submit', (event) => {event.preventDefault();document.querySelector('#status').textContent='Settings saved';});
else document.querySelector('#action')?.addEventListener('click', () => {document.querySelector('#status').textContent='Action completed';});
