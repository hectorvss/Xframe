import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";

export default function UsageChart({ config, series }) {
  return (
    <ChartContainer config={config} className="mt-6 h-[260px] w-full">
      <BarChart data={series} barCategoryGap={2}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
        />
        <YAxis tickLine={false} axisLine={false} width={28} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar dataKey="build" stackId="c" fill="var(--color-build)" radius={[0, 0, 0, 0]} />
        <Bar dataKey="run" stackId="c" fill="var(--color-run)" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ChartContainer>
  );
}
