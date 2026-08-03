import type { Story } from "@ladle/react";
import { useState } from "react";
import { IconPicker } from "./IconPicker";
import type { Icon as IconRef } from "./protocol";

export default { title: "IconPicker" };

export const LucideOpen: Story = () => {
  const [value, setValue] = useState<IconRef | null>(null);
  return (
    <div style={{ position: "relative", height: 600 }}>
      <IconPicker
        value={value}
        onChange={setValue}
        open
        onClose={() => {}}
      />
    </div>
  );
};

export const WithSelected: Story = () => {
  const [value, setValue] = useState<IconRef | null>({
    source: "lucide",
    name: "globe",
  });
  return (
    <div style={{ position: "relative", height: 600 }}>
      <IconPicker
        value={value}
        onChange={setValue}
        open
        onClose={() => {}}
      />
    </div>
  );
};

export const BrandsTab: Story = () => {
  const [value, setValue] = useState<IconRef | null>({
    source: "simple-icons",
    name: "github",
  });
  return (
    <div style={{ position: "relative", height: 600 }}>
      <IconPicker
        value={value}
        onChange={setValue}
        open
        onClose={() => {}}
      />
    </div>
  );
};
