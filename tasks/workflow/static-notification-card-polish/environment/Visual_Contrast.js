(selector) => {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d", {willReadFrequently: true});
  const rgba = value => {
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = value;
    context.fillRect(0, 0, 1, 1);
    return [...context.getImageData(0, 0, 1, 1).data].map(v => v / 255);
  };
  const over = (front, back) => {
    const alpha = front[3] + back[3] * (1 - front[3]);
    return alpha ? [
      ...front.slice(0, 3).map((v, i) =>
        (v * front[3] + back[i] * back[3] * (1 - front[3])) / alpha),
      alpha
    ] : [0, 0, 0, 0];
  };
  const luminance = color => color.slice(0, 3)
    .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  return [...document.querySelectorAll(selector)].map(element => {
    if (!element.checkVisibility({opacityProperty: true, visibilityProperty: true})
        || !element.getBoundingClientRect().width || !element.getBoundingClientRect().height) return 0;
    let foreground = rgba(getComputedStyle(element).color);
    let background = [0, 0, 0, 0];
    // Composite each nested background and group opacity, then the white browser canvas.
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      // The visible task contract bounds paint effects to solid-color compositing.
      if (style.backgroundImage !== 'none' || style.filter !== 'none'
          || style.backdropFilter !== 'none' || style.maskImage !== 'none'
          || style.clipPath !== 'none' || style.mixBlendMode !== 'normal') return 0;
      const paint = rgba(style.backgroundColor);
      foreground = over(foreground, paint);
      background = over(background, paint);
      foreground[3] *= Number(style.opacity);
      background[3] *= Number(style.opacity);
    }
    const front = luminance(over(foreground, [1, 1, 1, 1]));
    const back = luminance(over(background, [1, 1, 1, 1]));
    return (Math.max(front, back) + .05) / (Math.min(front, back) + .05);
  });
}
