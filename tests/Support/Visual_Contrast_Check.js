// Model-free checks for the exact browser-evaluated function frozen into each fixture.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
let paint = 'rgba(0,0,0,0)';
const canvas = {getContext: () => ({
  clearRect() {}, fillRect() {},
  set fillStyle(value) { paint = value; },
  getImageData() {
    const v = paint.match(/[\d.]+/g).map(Number);
    return {data: [...v.slice(0, 3), (v[3] ?? 1) * 255]};
  }
})};
const make = (color, backgroundColor, opacity = '1', parentElement = null) => ({
  color, backgroundColor, opacity, parentElement,
  backgroundImage: 'none', filter: 'none', backdropFilter: 'none', maskImage: 'none',
  clipPath: 'none', mixBlendMode: 'normal',
  checkVisibility: () => true, getBoundingClientRect: () => ({width: 100, height: 20})
});
let element;
const measure = vm.runInNewContext(source, {
  document: {createElement: () => canvas, querySelectorAll: () => [element]},
  getComputedStyle: e => e
});
element = make('rgb(0,0,0)', 'rgb(255,255,255)');
assert.equal(measure('p')[0], 21);
element.opacity = '0';
assert.equal(measure('p')[0], 1);
element = make('rgba(0,0,0,0)', 'rgb(255,255,255)');
assert.equal(measure('p')[0], 1);
element = make('rgba(0,0,0,0.9)', 'rgb(255,255,255)');
assert.ok(measure('p')[0] > 4.5); // Translucency is valid when actual contrast suffices.
element = make('rgb(0,0,0)', 'rgba(0,0,0,0)', '1', make('rgb(0,0,0)', 'rgb(255,255,255)', '0.1'));
assert.ok(measure('p')[0] < 4.5);
element.parentElement.opacity = '1';
assert.equal(measure('p')[0], 21);
element.checkVisibility = () => false;
assert.equal(measure('p')[0], 0);
element = make('rgb(0,0,0)', 'rgb(255,255,255)');
for (const [field, value] of Object.entries({
  backgroundImage: 'linear-gradient(#111,#111)', filter: 'opacity(0)',
  backdropFilter: 'brightness(0)', maskImage: 'url(mask.svg)',
  clipPath: 'inset(100%)', mixBlendMode: 'screen'
})) {
  const original = element[field];
  element[field] = value;
  assert.equal(measure('p')[0], 0);
  element[field] = original;
}
console.log('Visual alpha, ancestor opacity and visibility checks passed.');
