import VerifyEmailBox from '@/components/VerifyEmailBox'

interface Props {
  searchParams: Promise<{ email?: string }>
}

export default async function VerifyPage({ searchParams }: Props) {
  const { email = '' } = await searchParams
  return <VerifyEmailBox email={decodeURIComponent(email)} />
}
