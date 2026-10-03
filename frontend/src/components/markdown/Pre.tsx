interface PreProps {
  children?: React.ReactNode;
}

export default function Pre({ children }: PreProps) {
  return (
    <pre
      className="
          overflow-x-auto
          rounded-lg
          bg-gray-900
          p-4
          text-sm
          text-gray-100
        "
    >
      {children}
    </pre>
  );
}
