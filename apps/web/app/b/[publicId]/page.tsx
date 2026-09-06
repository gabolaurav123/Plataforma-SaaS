import { CustomerApp } from '@/components/platform/customer-app';
export default async function Page({
  params,
}: {
  params: Promise<{ publicId: string }>;
}) {
  const { publicId } = await params;
  return <CustomerApp publicId={publicId} />;
}
