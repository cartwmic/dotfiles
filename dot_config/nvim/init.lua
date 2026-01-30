-- bootstrap lazy.nvim, LazyVim and your plugins

require("config.lazy")

vim.opt.clipboard = "unnamedplus"

-- User Commands
vim.api.nvim_create_user_command("UserPutPKMSFileDateTimestampToClipboard", function(_)
  local time = vim.fn.strftime("%Y-%m-%d-%H%M%S")
  vim.fn.setreg("+", time)
end, {})

vim.api.nvim_create_user_command("UserPutCurrentTimestampToClipboard", function(_)
  local time = vim.fn.strftime("%H:%M:%S")
  vim.fn.setreg("+", time)
end, {})

vim.api.nvim_create_user_command("UserGitChangedFilesToQuickfix", function(_)
  -- Get all changed files: modified, staged, and untracked
  local files = {}
  local seen = {}

  -- Helper to add files from git command
  local function add_files(cmd)
    local output = vim.fn.system(cmd)
    if vim.v.shell_error == 0 then
      for file in output:gmatch("[^\r\n]+") do
        if file ~= "" and not seen[file] then
          seen[file] = true
          table.insert(files, file)
        end
      end
    end
  end

  -- Get unstaged changes (modified files)
  add_files("git diff --name-only")

  -- Get staged changes
  add_files("git diff --name-only --cached")

  -- Get untracked files
  add_files("git ls-files --others --exclude-standard")

  if #files == 0 then
    vim.notify("No changed files found", vim.log.levels.INFO)
    return
  end

  -- Create quickfix list entries
  local qf_list = {}
  for _, file in ipairs(files) do
    table.insert(qf_list, {
      filename = file,
      lnum = 1,
      col = 1,
      text = "Git changed file",
    })
  end

  -- Set quickfix list and open it
  vim.fn.setqflist(qf_list, "r")
  vim.cmd("copen")
  vim.notify(string.format("Added %d changed file(s) to quickfix list", #files), vim.log.levels.INFO)
end, {})
