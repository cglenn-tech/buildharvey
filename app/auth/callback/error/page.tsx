import Link from 'next/link'

export default function CallbackErrorPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="max-w-sm px-6 text-center">
        <p className="text-neutral-900 mb-4">
          This verification link is no longer valid.
        </p>
        <Link href="/verify" className="text-sm text-neutral-900 underline">
          Send another email
        </Link>
      </div>
    </div>
  )
}
