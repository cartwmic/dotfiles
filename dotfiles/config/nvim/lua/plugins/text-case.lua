return {
  {
    "johmsalas/text-case.nvim",
    event = "VeryLazy",
    config = function()
      vim.api.nvim_set_keymap("v", "gaa", "<cmd>TextCaseOpenTelescope<CR>", { desc = "Telescope Quick Change" })
    end,
  },
}
