local fzf = require("fzf-lua")

return {
  {
    "ibhagwan/fzf-lua",
    opts = {
      grep = {
        actions = {
          ["ctrl-alt-g"] = { fzf.actions.grep_lgrep },
        },
      },
    },
  },
}
