export function Sparkline({
  values,
  activeIndex,
  label,
}: {
  values: number[];
  activeIndex: number;
  label: string;
}) {
  const width = 320;
  const height = 84;
  const pad = 8;
  if (values.length === 0) return null;
  const max = Math.max(...values, 0);
  const span = Math.max(max, 1e-6);
  const coords = values.map((value, index) => {
    const x = pad + (index * (width - pad * 2)) / Math.max(values.length - 1, 1);
    const y = height - pad - (value / span) * (height - pad * 2);
    return { x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const active = coords[activeIndex];
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <path d={path} className="spark-line" />
      {active && <circle cx={active.x} cy={active.y} r="3.5" className="spark-dot" />}
    </svg>
  );
}
