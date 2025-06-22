return {
  "tadmccorkle/markdown.nvim",
  ft = "markdown", -- or 'event = "VeryLazy"'
  opts = {
    mappings = {
      inline_surround_toggle = "gbs", -- (string|boolean) toggle inline style
      inline_surround_toggle_line = "gbss", -- (string|boolean) line-wise toggle inline style
      inline_surround_delete = "gds", -- (string|boolean) delete emphasis surrounding cursor
      inline_surround_change = "gcs", -- (string|boolean) change emphasis surrounding cursor
      link_add = "gbl", -- (string|boolean) add link
      link_follow = "gbx", -- (string|boolean) follow link
      go_curr_heading = "gj]c", -- (string|boolean) set cursor to current section heading
      go_parent_heading = "gj]p", -- (string|boolean) set cursor to parent section heading
      go_next_heading = "gj]]", -- (string|boolean) set cursor to next section heading
      go_prev_heading = "gj[[", -- (string|boolean) set cursor to previous section heading
    },
    on_attach = function(bufnr)
      local map = vim.keymap.set
      local opts = { buffer = bufnr }
      map({ "n", "i" }, "<M-l><M-o>", "<Cmd>MDListItemBelow<CR>", opts)
      map({ "n", "i" }, "<M-L><M-O>", "<Cmd>MDListItemAbove<CR>", opts)
      map("n", "<M-c>", "<Cmd>MDTaskToggle<CR>", opts)
      map("x", "<M-c>", ":MDTaskToggle<CR>", opts)
    end,
  },
}
