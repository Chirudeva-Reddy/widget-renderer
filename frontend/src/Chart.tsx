import type { ReactElement } from "react";
import type { ChartNode } from "./api";

const colors: Record<string, string> = { blue: "#326899", purple: "#694b91", orange: "#a65926", green: "#3f7849", red: "#b34343", yellow: "#8d6f16", pink: "#a54571" };
const palette: string[] = ["blue", "green", "orange", "purple"];

export function Chart({ chart }: { chart: ChartNode }): ReactElement {
  const width: number = 640;
  const height: number = 240;
  const left: number = 54;
  const right: number = 20;
  const top: number = 20;
  const bottom: number = 42;
  const values: number[] = chart.points.flatMap((point) => point.values);
  const minimum: number = Math.min(0, ...values);
  const maximum: number = Math.max(0, ...values);
  const span: number = maximum - minimum || 1;
  const plotHeight: number = height - top - bottom;
  const plotWidth: number = width - left - right;
  const slot: number = plotWidth / chart.points.length;
  const y = (value: number): number => top + (maximum - value) / span * plotHeight;
  const zero: number = y(0);
  const barIndices: number[] = chart.series.flatMap((series, index) => series.type === "bar" ? [index] : []);
  const barWidth: number = Math.min(36, slot * 0.7 / Math.max(1, barIndices.length));
  const labelStride: number = Math.max(1, Math.ceil(chart.points.length / 8));

  return <figure className="chart-figure">
    <div className="chart-scroll" dir="ltr"><svg viewBox={`0 0 ${width} ${height}`} role="presentation" aria-hidden="true">
      <line x1={left} x2={width - right} y1={zero} y2={zero} stroke="#7d8976" />
      {chart.show_y_axis && <><text x={left - 8} y={top + 4} textAnchor="end">{maximum}</text><text x={left - 8} y={height - bottom} textAnchor="end">{minimum}</text></>}
      {chart.series.map((series, seriesIndex) => {
        const color: string = colors[series.color ?? palette[seriesIndex]];
        if (series.type === "line") {
          const points: string = chart.points.map((point, index) => `${left + slot * (index + 0.5)},${y(point.values[seriesIndex])}`).join(" ");
          return <g key={seriesIndex}><polyline points={points} fill="none" stroke={color} strokeWidth="3" />{chart.points.map((point, index) => <circle key={index} cx={left + slot * (index + 0.5)} cy={y(point.values[seriesIndex])} r="3" fill={color} />)}</g>;
        }
        const barIndex: number = barIndices.indexOf(seriesIndex);
        return <g key={seriesIndex}>{chart.points.map((point, index) => {
          const valueY: number = y(point.values[seriesIndex]);
          return <rect key={index} x={left + slot * (index + 0.5) + (barIndex - barIndices.length / 2) * barWidth} y={Math.min(valueY, zero)} width={barWidth} height={Math.abs(valueY - zero)} fill={color} />;
        })}</g>;
      })}
      {chart.points.map((point, index) => index % labelStride === 0 ? <text key={index} x={left + slot * (index + 0.5)} y={height - 14} textAnchor="middle">{point.label}</text> : null)}
    </svg></div>
    {chart.show_legend && <figcaption className="chart-legend">{chart.series.map((series, index) => <span key={index}><i aria-hidden="true" style={{ backgroundColor: colors[series.color ?? palette[index]] }} />{series.label} ({series.type})</span>)}</figcaption>}
    <details className="chart-data"><summary>View chart data</summary><div className="table-scroll"><table className="widget-table"><thead><tr><th scope="col">Category</th>{chart.series.map((series, index) => <th scope="col" key={index}>{series.label}</th>)}</tr></thead><tbody>{chart.points.map((point, index) => <tr key={index}><th scope="row" dir="auto">{point.label}</th>{point.values.map((value, valueIndex) => <td key={valueIndex}>{value}</td>)}</tr>)}</tbody></table></div></details>
  </figure>;
}
