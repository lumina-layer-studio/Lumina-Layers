function LoadingSpinner() {
  return (
    <div
      data-testid="loading-spinner"
      className="absolute inset-0 flex items-center justify-center bg-gray-950"
    >
      <div className="animate-spin h-8 w-8 border-2 border-gray-600 border-t-white rounded-full" />
    </div>
  );
}

export default LoadingSpinner;
