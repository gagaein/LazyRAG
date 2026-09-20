import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ get: vi.fn(), install: vi.fn(), restart: vi.fn() }));
vi.mock("../api/systemDependencies", () => ({ getPythonComponents: mocks.get, installPythonComponent: mocks.install }));
vi.mock("@/runtime/desktopBridge", () => ({ restartRuntime: mocks.restart }));
import PythonComponentDependencies, { RAGComponentNotice } from "./PythonComponentDependencies";
const missing = { id: "rag", installed: false, active: false, restartRequired: false,
  installSupported: true, installing: false, filename: "rag-test.zip", sizeBytes: 1048576 };
beforeEach(() => { vi.resetAllMocks(); mocks.get.mockResolvedValue([missing]); });
afterEach(cleanup);
it("downloads from a supplied URL and requires an explicit restart", async () => {
  const installed = { ...missing, installed: true, restartRequired: true };
  mocks.install.mockImplementation(async () => { mocks.get.mockResolvedValue([installed]); return installed; });
  mocks.restart.mockResolvedValue({ ok: true });
  render(<MemoryRouter><PythonComponentDependencies /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "安装组件" }));
  expect(screen.getByText("rag-test.zip")).toBeInTheDocument();
  const confirm = screen.getByRole("button", { name: /下载并安装/ });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByLabelText("组件下载地址"), { target: { value: "https://cdn.example/rag-test.zip" } });
  fireEvent.click(confirm);
  await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("rag", "https://cdn.example/rag-test.zip", expect.any(AbortSignal)));
  const restart = await screen.findByRole("button", { name: "重启本地服务" });
  expect(mocks.restart).not.toHaveBeenCalled();
  fireEvent.click(restart);
  await waitFor(() => expect(mocks.restart).toHaveBeenCalledOnce());
});
it("keeps installation available after a download fails", async () => {
  mocks.install.mockRejectedValue(new Error("checksum mismatch"));
  render(<MemoryRouter><PythonComponentDependencies /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "安装组件" }));
  fireEvent.change(screen.getByLabelText("组件下载地址"), { target: { value: "https://cdn.example/bad.zip" } });
  fireEvent.click(screen.getByRole("button", { name: /下载并安装/ }));
  await waitFor(() => expect(mocks.install).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByRole("button", { name: /下载并安装/ })).toBeEnabled());
  expect(mocks.restart).not.toHaveBeenCalled();
});
it("shows an install link for an unavailable knowledge component", async () => {
  render(<MemoryRouter><RAGComponentNotice /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "安装组件" })).toHaveAttribute("href", "/settings?section=system_tools#python-rag-dependency");
});
