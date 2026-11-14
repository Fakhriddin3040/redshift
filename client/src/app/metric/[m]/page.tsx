import { notFound } from "next/navigation";
import { MetricView } from "@/components/MetricView";
import { METRIC_KEYS, isMetricKey } from "@/lib/format";

export function generateStaticParams() {
  return METRIC_KEYS.map((m) => ({ m }));
}

export default async function MetricPage({ params }: PageProps<"/metric/[m]">) {
  const { m } = await params;
  if (!isMetricKey(m)) notFound();
  return <MetricView m={m} />;
}
