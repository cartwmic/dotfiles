return {
  "cbochs/grapple.nvim",
  dependencies = {
    { "nvim-tree/nvim-web-devicons", lazy = true },
  },
  opts = {
    scope = "git", -- also try out "git_branch"
  },
  event = { "BufReadPost", "BufNewFile" },
  cmd = "Grapple",
  keys = {
    { "<leader>zg", "", desc = "Grapple" },
    { "<leader>zgm", "<cmd>Grapple toggle<cr>", desc = "Grapple toggle tag" },
    { "<leader>zgM", "<cmd>Grapple toggle_tags<cr>", desc = "Grapple open tags window" },
    { "<leader>zgn", "<cmd>Grapple cycle_tags next<cr>", desc = "Grapple cycle next tag" },
    { "<leader>zgp", "<cmd>Grapple cycle_tags prev<cr>", desc = "Grapple cycle previous tag" },
    { "<leader>1", "<cmd>Grapple select index=1<cr>", desc = "Grapple Select first tag" },
    { "<leader>2", "<cmd>Grapple select index=2<cr>", desc = "Grapple Select second tag" },
    { "<leader>3", "<cmd>Grapple select index=3<cr>", desc = "Grapple Select third tag" },
    { "<leader>4", "<cmd>Grapple select index=4<cr>", desc = "Grapple Select fourth tag" },
    { "<leader>5", "<cmd>Grapple select index=5<cr>", desc = "Grapple Select fifth tag" },
  },
}
