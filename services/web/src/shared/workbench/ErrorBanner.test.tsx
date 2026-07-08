import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBanner } from "./ErrorBanner";

describe("ErrorBanner", () => {
  it("renders nothing when error is null", () => {
    const { container } = render(<ErrorBanner error={null} onDismiss={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows error text and dismisses on click", () => {
    const onDismiss = vi.fn();
    render(<ErrorBanner error="发送失败：network" onDismiss={onDismiss} />);
    expect(screen.getByTestId("workbench-error").textContent).toContain("发送失败：network");
    fireEvent.click(screen.getByLabelText("关闭错误提示"));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
