import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import BaseModal from "@/components/common/BaseModal.vue";

describe("BaseModal", () => {
  it("renders nothing when closed", () => {
    const wrapper = mount(BaseModal, {
      props: { open: false, title: "T" },
      slots: { default: "body" },
    });
    expect(wrapper.find(".modal-backdrop").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("body");
  });

  it("renders title and body when open", () => {
    const wrapper = mount(BaseModal, {
      props: { open: true, title: "Confirm" },
      slots: { default: "Body content" },
    });
    expect(wrapper.find(".modal-backdrop").exists()).toBe(true);
    expect(wrapper.find(".modal-header h3").text()).toBe("Confirm");
    expect(wrapper.text()).toContain("Body content");
  });

  it("emits close and update:open(false) when close button clicked", async () => {
    const wrapper = mount(BaseModal, {
      props: { open: true, closable: true, title: "Confirm" },
      slots: { default: "Body content" },
    });
    await wrapper.find(".modal-header button").trigger("click");
    expect(wrapper.emitted("close")).toBeTruthy();
    const update = wrapper.emitted("update:open");
    expect(update).toBeTruthy();
    expect(update![0][0]).toBe(false);
  });

  it("omits close button when closable is false", () => {
    const wrapper = mount(BaseModal, {
      props: { open: true, closable: false, title: "Confirm" },
    });
    expect(wrapper.find(".modal-header button").exists()).toBe(false);
  });

  it("applies custom width style", () => {
    const wrapper = mount(BaseModal, {
      props: { open: true, width: "600px" },
      slots: { default: "b" },
    });
    expect(wrapper.find(".modal").attributes("style")).toContain("width: 600px");
  });
});
