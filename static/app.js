let rootDir = ""
let currentFolder = null
let currentPath = ""

let page = 0
let loading = false
let hasMore = true

let imageList = []
let currentIndex = -1

let scale = 1
let isDragging = false
let startX = 0
let startY = 0
let translateX = 0
let translateY = 0
let savedRoots = JSON.parse(localStorage.getItem("savedRoots") || "[]")

// 选择模式相关
let selectMode = false
let selectedImages = new Set()
let imageFilenameMap = new Map() // 存储 img index -> filename 的映射

// JSON 模式相关
let jsonMode = false
let jsonPath = ""
let jsonKeys = []
let jsonSelectedKeys = []  // 多选 key 列表
let jsonPage = 0
let jsonHasMore = true
let jsonLoading = false
let jsonImageList = [] // JSON 模式下的图片列表（用于查看器导航）

let jsonItemImageMap = {} // item index -> { fullUrls: [], label: str }
let multiScale = 1   // 多图查看器缩放
let multiDragState = { dragging: false, startX: 0, startY: 0 }

const gallery = document.getElementById("gallery")
const folderList = document.getElementById("folderList")

const viewer = document.getElementById("viewer")
const viewerImg = document.getElementById("viewerImg")
const keyHelp = document.getElementById("keyHelp")

const content = document.querySelector(".content")
const savedRootsDiv = document.getElementById("savedRoots")

const backBtn = document.getElementById("backBtn")
const imageInfo = document.getElementById("imageInfo")

// ============================================================
// 根目录加载
// ============================================================

async function loadRoot(){
  const inputVal = document.getElementById("rootInput").value.trim()

  // 判断是否是 JSON 文件
  if (inputVal.toLowerCase().endsWith(".json")) {
    await loadJsonFile(inputVal)
    return
  }

  // 普通文件夹模式
  exitJsonMode()

  rootDir = inputVal

  folderList.innerHTML = ""
  gallery.innerHTML = ""

  currentFolder = ""
  currentPath = ""

  const res = await fetch(`/api/folders?root_dir=${encodeURIComponent(rootDir)}`)
  const data = await res.json()

  renderFolders(data.folders)
  selectFolder("")
}


function renderFolders(folders){

folderList.innerHTML = ""

folders.forEach(folder => {

const li = document.createElement("li")
li.innerText = folder

li.onclick = ()=>{
enterFolder(folder)
}

folderList.appendChild(li)

})

}


async function enterFolder(folder){

const newPath = currentPath ? currentPath + "/" + folder : folder

currentPath = newPath

updateURL()

const res = await fetch(
`/api/folders?root_dir=${encodeURIComponent(rootDir)}&path=${encodeURIComponent(newPath)}`
)

const data = await res.json()

renderFolders(data.folders)

selectFolder(newPath)

}


function updateURL(){

const params = new URLSearchParams()

if(rootDir){
params.set("root", rootDir)
}

if(currentPath){
params.set("path", currentPath)
}

if(jsonMode){
  params.set("json", jsonPath)
  if(jsonSelectedKeys.length > 0){
    params.set("key", jsonSelectedKeys.join(","))
  }
}

const newUrl = window.location.pathname + "?" + params.toString()

history.replaceState(null,"",newUrl)

}


function goBack(){

  if(jsonMode){
    // JSON 模式下返回 key 选择
    if(jsonSelectedKeys.length > 0){
      jsonSelectedKeys = []
      gallery.innerHTML = ""
      gallery.classList.add("json-mode")
      document.getElementById("jsonModeBar").style.display = "none"
      // 重新高亮 key 列表
      document.querySelectorAll(".json-key-item").forEach(el => el.classList.remove("active"))
      return
    } else {
      exitJsonMode()
      // 退出后重新加载根目录
      if(rootDir){
        loadRoot()
      }
      return
    }
  }

if(!currentPath){
loadRoot()
return
}

const parts = currentPath.split("/")
parts.pop()

const newPath = parts.join("/")

currentPath = newPath

loadFolderPath(newPath)

}


async function loadFolderPath(path){

const res = await fetch(
`/api/folders?root_dir=${encodeURIComponent(rootDir)}&path=${encodeURIComponent(path)}`
)

const data = await res.json()

renderFolders(data.folders)

if(path){
selectFolder(path)
}else{
gallery.innerHTML = ""
}

}



function selectFolder(folder){

currentFolder = folder
currentPath = folder

page = 0
hasMore = true

imageList = []
currentIndex = -1

gallery.innerHTML = ""

loadImages()

}


async function loadImages(){

if(!hasMore || loading) return

loading = true

const res = await fetch(
`/api/images?root_dir=${encodeURIComponent(rootDir)}&folder=${encodeURIComponent(currentFolder || "")}&page=${page}`
)

const data = await res.json()

data.images.forEach(url => {

const index = imageList.length
imageList.push(url)

const div = document.createElement("div")
div.className = "img-box"

const img = document.createElement("img")

img.src = url
img.loading = "lazy"

img.onclick = ()=>{
if(selectMode){
toggleImageSelection(index, div)
}else{
openViewer(index)
}
}

div.appendChild(img)

// 在选择模式下添加复选框
if(selectMode){
const checkbox = document.createElement("input")
checkbox.type = "checkbox"
checkbox.className = "img-checkbox"
checkbox.checked = selectedImages.has(index)
checkbox.onclick = (e)=>{
e.stopPropagation()
toggleImageSelection(index, div)
}
div.appendChild(checkbox)
}

gallery.appendChild(div)

})

hasMore = data.has_more
page += 1
loading = false

}


// ============================================================
// JSON 模式
// ============================================================

async function loadJsonFile(path) {
  jsonPath = path
  jsonMode = true
  jsonSelectedKeys = []
  jsonImageList = []

  // 隐藏文件夹相关区域，显示 JSON key 面板
  folderList.innerHTML = ""
  document.querySelector(".folder-panel").style.display = "none"
  document.querySelector(".folder-toolbar").style.display = "none"
  gallery.innerHTML = ""
  gallery.classList.add("json-mode")

  const jsonKeyPanel = document.getElementById("jsonKeyPanel")
  const jsonKeyList = document.getElementById("jsonKeyList")
  const jsonInfoEl = document.getElementById("jsonInfo")
  const jsonModeBar = document.getElementById("jsonModeBar")

  jsonKeyPanel.style.display = "block"
  jsonModeBar.style.display = "none"
  jsonKeyList.innerHTML = "<div style='color:#888;font-size:12px;'>加载中...</div>"

  const res = await fetch(`/api/json_info?json_path=${encodeURIComponent(path)}`)
  const data = await res.json()

  if (data.error) {
    jsonKeyList.innerHTML = `<div style="color:#ff6b6b;font-size:12px;">错误: ${data.error}</div>`
    return
  }

  jsonKeys = data.keys
  jsonInfoEl.textContent = `共 ${data.total_items} 条记录，${data.keys.length} 个图片 Key`

  if (data.keys.length === 0) {
    jsonKeyList.innerHTML = "<div style='color:#888;font-size:12px;'>未找到图片路径字段</div>"
    return
  }

  // 渲染 key 按钮
  jsonKeyList.innerHTML = ""
  data.keys.forEach(key => {
    const btn = document.createElement("div")
    btn.className = "json-key-item"
    btn.textContent = key
    btn.onclick = () => selectJsonKey(key)
    jsonKeyList.appendChild(btn)
  })

  updateURL()
}


function selectJsonKey(key) {
  const idx = jsonSelectedKeys.indexOf(key)
  if (idx >= 0) {
    // 取消选中
    jsonSelectedKeys.splice(idx, 1)
  } else {
    // 选中
    jsonSelectedKeys.push(key)
  }

  // 更新 key 按钮高亮
  document.querySelectorAll(".json-key-item").forEach(el => {
    el.classList.toggle("active", jsonSelectedKeys.includes(el.textContent))
  })

  if (jsonSelectedKeys.length === 0) {
    // 没有选中的 key，清空画廊
    gallery.innerHTML = ""
    document.getElementById("jsonModeBar").style.display = "none"
    return
  }

  // 重新加载
  jsonPage = 0
  jsonHasMore = true
  jsonLoading = false
  jsonImageList = []

  // 显示模式提示栏
  const jsonModeBar = document.getElementById("jsonModeBar")
  const jsonModeLabel = document.getElementById("jsonModeLabel")
  jsonModeBar.style.display = "flex"
  jsonModeLabel.textContent = `📷 Keys: ${jsonSelectedKeys.join(", ")}`

  gallery.innerHTML = ""
  loadJsonImages()

  updateURL()
}


async function loadJsonImages() {
  if (!jsonHasMore || jsonLoading) return
  jsonLoading = true

  const keysParam = jsonSelectedKeys.join(",")
  const res = await fetch(
    `/api/json_images?json_path=${encodeURIComponent(jsonPath)}&key=${encodeURIComponent(keysParam)}&page=${jsonPage}`
  )
  const data = await res.json()

  // 更新计数
  const jsonItemCount = document.getElementById("jsonItemCount")
  jsonItemCount.textContent = `共 ${data.total_filtered} 条匹配`

  data.items.forEach((item, itemIdx) => {
    // 创建分组卡片
    // 收集该 item 所有图片的完整 URL（用于多图查看器）
    const globalItemIndex = Object.keys(jsonItemImageMap).length
    const allFullUrls = []
    const selImgs = item.selected_images || {}
    Object.values(selImgs).forEach(urls => {
      if (Array.isArray(urls)) {
        urls.forEach(u => allFullUrls.push(u.replace("/json_image?", "/json_image_full?")))
      }
    })
    const othImgs = item.other_images || {}
    Object.values(othImgs).forEach(urls => {
      if (Array.isArray(urls)) {
        urls.forEach(u => allFullUrls.push(u.replace("/json_image?", "/json_image_full?")))
      }
    })
    jsonItemImageMap[globalItemIndex] = {
      fullUrls: allFullUrls,
      label: item.group ? `${item.group} #${item.sub_index !== undefined ? item.sub_index : item.index}` : `#${item.index}`
    }

    const group = document.createElement("div")
    group.className = "json-item-group"

    // 头部：item 索引 + 未选中的其他 key 标签
    const header = document.createElement("div")
    header.className = "json-item-header"

    const indexBadge = document.createElement("span")
    indexBadge.className = "json-item-index"
    indexBadge.textContent = item.group ? `${item.group} #${item.sub_index !== undefined ? item.sub_index : item.index}` : `#${item.index}`
    header.appendChild(indexBadge)
    indexBadge.style.cursor = "pointer"
    indexBadge.title = "点击查看该 item 所有图片排列"
    indexBadge.onclick = (e) => {
      e.stopPropagation()
      openMultiViewer(globalItemIndex)
    }

    // 未选中的其他图片 key 标签（可点击加入选择）
    const otherKeys = Object.keys(item.other_images || {})
    if (otherKeys.length > 0) {
      const otherKeysDiv = document.createElement("div")
      otherKeysDiv.className = "json-item-other-keys"
      otherKeys.forEach(k => {
        const tag = document.createElement("span")
        tag.className = "json-item-other-key"
        tag.textContent = `+ ${k}`
        tag.title = "点击添加此 Key"
        tag.onclick = (e) => {
          e.stopPropagation()
          if (!jsonSelectedKeys.includes(k)) {
            selectJsonKey(k)
          }
        }
        otherKeysDiv.appendChild(tag)
      })
      header.appendChild(otherKeysDiv)
    }

    group.appendChild(header)

    // 按 key 分列并列展示
    const selectedImages = item.selected_images || {}
    const selectedKeys = Object.keys(selectedImages)

    if (selectedKeys.length > 0) {
      const columnsDiv = document.createElement("div")
      columnsDiv.className = "json-key-columns"
      columnsDiv.style.display = "flex"
      columnsDiv.style.gap = "16px"
      columnsDiv.style.flexWrap = "wrap"

      selectedKeys.forEach(key => {
        const columnDiv = document.createElement("div")
        columnDiv.className = "json-key-column"

        // key 标签
        const keyLabel = document.createElement("div")
        keyLabel.className = "json-column-label"
        keyLabel.textContent = key
        columnDiv.appendChild(keyLabel)

        // 该 key 下的图片
        const imagesDiv = document.createElement("div")
        imagesDiv.className = "json-item-images"

        const urls = selectedImages[key]
        urls.forEach(url => {
          const jsonIndex = jsonImageList.length
          const fullUrl = url.replace("/json_image?", "/json_image_full?")
          jsonImageList.push({ thumb: url, full: fullUrl, key: key })

          const div = document.createElement("div")
          div.className = "img-box"

          const img = document.createElement("img")
          img.src = url
          img.loading = "lazy"
          img.onclick = () => openJsonViewer(jsonIndex)

          div.appendChild(img)
          imagesDiv.appendChild(div)
        })

        columnDiv.appendChild(imagesDiv)
        columnsDiv.appendChild(columnDiv)
      })

      group.appendChild(columnsDiv)
    }

    gallery.appendChild(group)
  })

  jsonHasMore = data.has_more
  jsonPage += 1
  jsonLoading = false
}



// ============================================================
// 多图排列查看器
// ============================================================

function openMultiViewer(itemIndex) {
  const data = jsonItemImageMap[itemIndex]
  if (!data) return

  const viewerEl = document.getElementById("multiViewer")
  const grid = document.getElementById("multiViewerGrid")
  grid.innerHTML = ""
  multiScale = 1

  data.fullUrls.forEach(url => {
    const box = document.createElement("div")
    box.className = "multi-img-box"
    const img = document.createElement("img")
    img.src = url
    img.loading = "lazy"
    img.draggable = false
    img.onclick = (e) => {
      e.stopPropagation()
      window.open(url, "_blank")
    }
    box.appendChild(img)
    grid.appendChild(box)
  })

  viewerEl.classList.add("open")

  // 初始自适应缩放
  setTimeout(() => {
    const gridWidth = grid.scrollWidth
    const containerWidth = viewerEl.clientWidth - 48
    if (gridWidth > containerWidth && gridWidth > 0) {
      multiScale = containerWidth / gridWidth
    } else {
      multiScale = 1
    }
    applyMultiScale(grid)
  }, 150)

  // 滚轮缩放
  viewerEl._wheelHandler = (e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.05 : 0.05
    multiScale += delta
    applyMultiScale(grid)
  }
  viewerEl.addEventListener("wheel", viewerEl._wheelHandler, { passive: false })

  // 鼠标拖动
  viewerEl._mouseDown = (e) => {
    if (e.target.closest(".multi-viewer-close")) return
    e.preventDefault()
    multiDragState.dragging = true
    multiDragState.startX = e.clientX + viewerEl.scrollLeft
    multiDragState.startY = e.clientY + viewerEl.scrollTop
    viewerEl.style.cursor = "grabbing"
  }
  viewerEl.addEventListener("mousedown", viewerEl._mouseDown)

  viewerEl._mouseMove = (e) => {
    if (!multiDragState.dragging) return
    e.preventDefault()
    viewerEl.scrollLeft = multiDragState.startX - e.clientX
    viewerEl.scrollTop = multiDragState.startY - e.clientY
  }
  viewerEl.addEventListener("mousemove", viewerEl._mouseMove)

  viewerEl._mouseUp = () => {
    multiDragState.dragging = false
    viewerEl.style.cursor = "grab"
  }
  viewerEl.addEventListener("mouseup", viewerEl._mouseUp)
}

function applyMultiScale(grid) {
  multiScale = Math.max(0.1, Math.min(5, multiScale))
  grid.style.transform = `scale(${multiScale})`
}

function closeMultiViewer() {
  const viewerEl = document.getElementById("multiViewer")
  viewerEl.classList.remove("open")
  document.getElementById("multiViewerGrid").innerHTML = ""
  multiScale = 1

  if (viewerEl._wheelHandler) {
    viewerEl.removeEventListener("wheel", viewerEl._wheelHandler)
    viewerEl._wheelHandler = null
  }
  if (viewerEl._mouseDown) {
    viewerEl.removeEventListener("mousedown", viewerEl._mouseDown)
    viewerEl._mouseDown = null
  }
  if (viewerEl._mouseMove) {
    viewerEl.removeEventListener("mousemove", viewerEl._mouseMove)
    viewerEl._mouseMove = null
  }
  if (viewerEl._mouseUp) {
    viewerEl.removeEventListener("mouseup", viewerEl._mouseUp)
    viewerEl._mouseUp = null
  }
}

function exitJsonMode() {
  jsonMode = false
  jsonPath = ""
  jsonKeys = []
  jsonSelectedKeys = []
  jsonImageList = []

  document.getElementById("jsonKeyPanel").style.display = "none"
  document.getElementById("jsonModeBar").style.display = "none"
  document.querySelector(".folder-panel").style.display = ""
  document.querySelector(".folder-toolbar").style.display = ""
  gallery.classList.remove("json-mode")
}


function openJsonViewer(index) {
  currentIndex = index
  const item = jsonImageList[index]
  viewerImg.src = item.full
  viewer.style.display = "flex"
  keyHelp.style.display = "block"
  resetTransform()

  // 简单的图片信息
  imageInfo.innerHTML = `<b>JSON 图片</b><br>Index: ${index + 1} / ${jsonImageList.length}`
}


// ============================================================
// 查看器
// ============================================================

async function openViewer(index){

currentIndex = index

const url = imageList[index]

viewerImg.src = url.replace("/thumb","/image")

viewer.style.display = "flex"

keyHelp.style.display = "block"

resetTransform()

const params = new URL(url, window.location.origin).searchParams

const filename = params.get("filename")

const res = await fetch(
`/api/image_info?root_dir=${encodeURIComponent(rootDir)}&folder=${encodeURIComponent(currentFolder || "")}&filename=${encodeURIComponent(filename)}`
)

const data = await res.json()

if(!data.error){

imageInfo.innerHTML =
`<b>${data.filename}</b><br>
${data.width} × ${data.height}<br>
channels: ${data.channels}`

}

}


function closeViewer(){

viewer.style.display = "none"
viewerImg.src = ""

keyHelp.style.display = "none"

}


function resetTransform(){

scale = 1
translateX = 0
translateY = 0

updateTransform()

}


function updateTransform(){

viewerImg.style.transform =
`translate(${translateX}px, ${translateY}px) scale(${scale})`

}


function prevImage(){
  if (jsonMode) {
    if (currentIndex <= 0) return
    currentIndex -= 1
    const item = jsonImageList[currentIndex]
    viewerImg.src = item.full
    updateTransform()
    imageInfo.innerHTML = `<b>JSON 图片</b><br>Index: ${currentIndex + 1} / ${jsonImageList.length}`
    return
  }

if(currentIndex <= 0) return

currentIndex -= 1

const url = imageList[currentIndex]

viewerImg.src = url.replace("/thumb","/image")

updateTransform()

}


function nextImage(){
  if (jsonMode) {
    if (currentIndex >= jsonImageList.length - 1) return
    currentIndex += 1
    const item = jsonImageList[currentIndex]
    viewerImg.src = item.full
    updateTransform()
    imageInfo.innerHTML = `<b>JSON 图片</b><br>Index: ${currentIndex + 1} / ${jsonImageList.length}`
    return
  }

if(currentIndex >= imageList.length - 1) return

currentIndex += 1

const url = imageList[currentIndex]

viewerImg.src = url.replace("/thumb","/image")

updateTransform()

}


document.addEventListener("keydown",(e)=>{

if(viewer.style.display !== "flex") return

if(e.key === "ArrowLeft" || e.key === "a"){
prevImage()
}

if(e.key === "ArrowRight" || e.key === "d"){
nextImage()
}

if(e.key === "Escape"){
  const mv = document.getElementById("multiViewer")
  if (mv.classList.contains("open")) {
    closeMultiViewer()
  } else {
    closeViewer()
  }
}

})


// 多图查看器：点击背景关闭
document.getElementById("multiViewer").addEventListener("click", (e) => {
  if (e.target.id === "multiViewer") {
    closeMultiViewer()
  }
})

viewer.addEventListener("click",(e)=>{

if(e.target === viewer){
closeViewer()
}

})


viewerImg.addEventListener("wheel",(e)=>{

e.preventDefault()

const delta = e.deltaY > 0 ? -0.1 : 0.1

scale += delta

if(scale < 0.2) scale = 0.2
if(scale > 5) scale = 5

updateTransform()

})


viewerImg.addEventListener("mousedown",(e)=>{

isDragging = true

startX = e.clientX - translateX
startY = e.clientY - translateY

viewerImg.style.cursor = "grabbing"

})


document.addEventListener("mousemove",(e)=>{

if(!isDragging) return

translateX = e.clientX - startX
translateY = e.clientY - startY

updateTransform()

})


document.addEventListener("mouseup",()=>{

isDragging = false

viewerImg.style.cursor = "grab"

})


content.addEventListener("scroll",()=>{

const nearBottom =
content.scrollTop + content.clientHeight >= content.scrollHeight - 200

if(nearBottom){
  if(jsonMode){
    loadJsonImages()
  } else {
    loadImages()
  }
}

})


function saveRoot(){

const input = document.getElementById("rootInput")
const path = input.value.trim()

if(!path) return

if(!savedRoots.includes(path)){
savedRoots.push(path)
localStorage.setItem("savedRoots", JSON.stringify(savedRoots))
}

renderSavedRoots()

}


function renderSavedRoots(){

const container = document.getElementById("savedRoots")
container.innerHTML = ""

savedRoots.forEach((path,index)=>{

const item = document.createElement("div")

const pathSpan = document.createElement("span")
pathSpan.className = "root-path"
pathSpan.textContent = path

pathSpan.onclick = ()=>{
document.getElementById("rootInput").value = path
loadRoot()
}

const removeBtn = document.createElement("span")
removeBtn.className = "root-remove"
removeBtn.textContent = "✕"

removeBtn.onclick = (e)=>{
e.stopPropagation()

savedRoots.splice(index,1)

localStorage.setItem("savedRoots",JSON.stringify(savedRoots))

renderSavedRoots()
}

item.appendChild(pathSpan)
item.appendChild(removeBtn)

container.appendChild(item)

})

}

backBtn.onclick = ()=>{
goBack()
}

async function restoreFromURL(){

const params = new URLSearchParams(window.location.search)

const root = params.get("root")
const path = params.get("path")
const json = params.get("json")
const key = params.get("key")

// 优先恢复 JSON 模式
if(json){
  document.getElementById("rootInput").value = json
  await loadJsonFile(json)
  if(key){
    const keys = key.split(",")
    keys.forEach(k => selectJsonKey(k.trim()))
  }
  return
}
if(!root) return

document.getElementById("rootInput").value = root

rootDir = root

const res = await fetch(`/api/folders?root_dir=${encodeURIComponent(root)}`)
const data = await res.json()

renderFolders(data.folders)

if(path){

currentPath = path

loadFolderPath(path)

}

}

renderSavedRoots()
restoreFromURL()

// ============================================================
// 选择模式与删除功能
// ============================================================

function toggleSelectMode(){
selectMode = !selectMode
selectedImages.clear()

const selectBtn = document.getElementById("selectBtn")
const deleteBtn = document.getElementById("deleteBtn")
const cancelBtn = document.getElementById("cancelSelectBtn")
const selectCount = document.getElementById("selectCount")
const selectAllBtn = document.getElementById("selectAllBtn")
const deselectAllBtn = document.getElementById("deselectAllBtn")

if(selectMode){
selectBtn.textContent = "取消选择"
selectBtn.classList.add("active")
deleteBtn.style.display = "inline-block"
cancelBtn.style.display = "inline-block"
selectAllBtn.style.display = "inline-block"
deselectAllBtn.style.display = "inline-block"
}else{
selectBtn.textContent = "选择"
selectBtn.classList.remove("active")
deleteBtn.style.display = "none"
cancelBtn.style.display = "none"
selectAllBtn.style.display = "none"
deselectAllBtn.style.display = "none"
selectCount.textContent = ""
}

// 重新渲染所有图片的复选框
refreshAllCheckboxes()
updateSelectedCount()
}


function refreshAllCheckboxes(){
const boxes = gallery.querySelectorAll(".img-box")
boxes.forEach((div, i)=>{
// 跳过已在页面上的复选框处理
const existingCheckbox = div.querySelector(".img-checkbox")
if(selectMode && !existingCheckbox){
const checkbox = document.createElement("input")
checkbox.type = "checkbox"
checkbox.className = "img-checkbox"
checkbox.checked = selectedImages.has(i)
checkbox.onclick = (e)=>{
e.stopPropagation()
toggleImageSelection(i, div)
}
div.appendChild(checkbox)
}else if(!selectMode && existingCheckbox){
existingCheckbox.remove()
}

if(selectMode){
div.classList.toggle("selected", selectedImages.has(i))
}
})
}


function toggleImageSelection(index, div){
if(selectedImages.has(index)){
selectedImages.delete(index)
div.classList.remove("selected")
}else{
selectedImages.add(index)
div.classList.add("selected")
}

// 更新复选框状态
const checkbox = div.querySelector(".img-checkbox")
if(checkbox){
checkbox.checked = selectedImages.has(index)
}

updateSelectedCount()
}


function updateSelectedCount(){
const selectCount = document.getElementById("selectCount")
if(selectedImages.size > 0){
selectCount.textContent = `已选择 ${selectedImages.size} 张图片`
}else{
selectCount.textContent = ""
}
}


async function deleteSelectedImages(){
if(selectedImages.size === 0){
alert("请先选择要删除的图片")
return
}

const confirmed = confirm(`确定要删除选中的 ${selectedImages.size} 张图片吗？
此操作不可恢复！`)

if(!confirmed) return

const filenames = []
selectedImages.forEach(index=>{
// 从 URL 中提取 filename
const url = imageList[index]
const params = new URL(url, window.location.origin).searchParams
filenames.push(params.get("filename"))
})

try{
const res = await fetch(
`/api/delete_images?root_dir=${encodeURIComponent(rootDir)}&folder=${encodeURIComponent(currentFolder || "")}`,
{
method: "POST",
headers: {"Content-Type": "application/json"},
body: JSON.stringify({filenames})
}
)

const data = await res.json()

if(data.total_deleted > 0){
alert(`成功删除 ${data.total_deleted} 张图片`)
if(data.total_errors > 0){
alert(`删除过程中有 ${data.total_errors} 个错误`)
}
}else{
alert("删除失败")
console.error(data.errors)
}

// 重新加载当前文件夹
exitSelectMode()
refreshGallery()

}catch(e){
console.error("删除请求失败:", e)
alert("删除请求失败，请检查网络连接")
}
}


function exitSelectMode(){
selectMode = false
selectedImages.clear()

const selectBtn = document.getElementById("selectBtn")
const deleteBtn = document.getElementById("deleteBtn")
const cancelBtn = document.getElementById("cancelSelectBtn")
const selectAllBtn = document.getElementById("selectAllBtn")
const deselectAllBtn = document.getElementById("deselectAllBtn")

selectBtn.textContent = "选择"
selectBtn.classList.remove("active")
deleteBtn.style.display = "none"
cancelBtn.style.display = "none"
selectAllBtn.style.display = "none"
deselectAllBtn.style.display = "none"
document.getElementById("selectCount").textContent = ""

refreshAllCheckboxes()
}


async function refreshGallery(){
// 保存当前滚动位置
const scrollTop = content.scrollTop

// 清空并重新加载
gallery.innerHTML = ""
imageList = []
page = 0
hasMore = true
currentIndex = -1

await loadImages()

// 恢复滚动位置
content.scrollTop = scrollTop
}

// 全选功能
function selectAll(){
const boxes = gallery.querySelectorAll(".img-box")
boxes.forEach((div, i)=>{
if(!selectedImages.has(i)){
selectedImages.add(i)
div.classList.add("selected")
const checkbox = div.querySelector(".img-checkbox")
if(checkbox) checkbox.checked = true
}
})
updateSelectedCount()
}

// 取消全选功能
function deselectAll(){
selectedImages.clear()
const boxes = gallery.querySelectorAll(".img-box")
boxes.forEach(div=>{
div.classList.remove("selected")
const checkbox = div.querySelector(".img-checkbox")
if(checkbox) checkbox.checked = false
})
updateSelectedCount()
}