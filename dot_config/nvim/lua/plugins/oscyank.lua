return {
  {
    "ojroques/nvim-osc52",
    config = function(_, _)
      vim.keymap.set("v", "<leader>C", require("osc52").copy_visual, { desc = "Copy Selection via OSC52" })
    end,
  },
}
