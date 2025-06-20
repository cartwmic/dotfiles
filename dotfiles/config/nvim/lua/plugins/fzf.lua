local fzf = require("fzf-lua")

return {
  {
    "ibhagwan/fzf-lua",
    keys = {
      { "<c-o>", "<c-\\><c-n>", ft = "fzf", mode = "t", nowait = true }, -- go to normal mode in fzf floating window (not for editing)
    },
    opts = {
      grep = {
        actions = {
          ["ctrl-alt-g"] = { fzf.actions.grep_lgrep },
        },
      },
    },
  },
}
