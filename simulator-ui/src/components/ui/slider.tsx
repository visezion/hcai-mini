import { useEffect, useState } from "react";
import { cn } from "../../lib/utils";

interface SliderProps {
  defaultValue?: number[];
  min?: number;
  max?: number;
  step?: number;
  className?: string;
  onValueChange?: (value: number[]) => void;
}

export function Slider({
  defaultValue = [0],
  min = 0,
  max = 100,
  step = 1,
  className,
  onValueChange,
}: SliderProps) {
  const [value, setValue] = useState(defaultValue[0]);

  useEffect(() => {
    setValue(defaultValue[0]);
  }, [defaultValue]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = Number(event.target.value);
    setValue(next);
    onValueChange?.([next]);
  };

  return (
    <div className={cn("w-full", className)}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={handleChange}
        className="w-full accent-primary"
      />
    </div>
  );
}
