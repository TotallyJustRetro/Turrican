#include "mt_level_builder_importer.h"

#include <assimp/Importer.hpp>
#include <assimp/scene.h>
#include <assimp/postprocess.h>
#include <SDL.h>
#include <SDL_image.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>

namespace fs = std::filesystem;
namespace {
constexpr int kMaxImportedModels = 64;
constexpr int kMaxImportedTextures = 64;
constexpr int kPreviewTriangles = 512;

struct ImportedModel {
    char name[128] = {};
    char path[1024] = {};
    char format[16] = {};
    char diffuse[512] = {};
    char normal[512] = {};
    char emissive[512] = {};
    uint32_t triangles = 0;
    uint32_t bones = 0;
    float bounds[3] = {0,0,0};
    int classification = 0;
    int preview_vertices = 0;
    std::array<float, kPreviewTriangles * 9> preview_xyz = {};
};
struct ImportedTexture {
    char name[128] = {};
    char path[1024] = {};
    int width = 0;
    int height = 0;
};
static ImportedModel g_models[kMaxImportedModels];
static ImportedTexture g_textures[kMaxImportedTextures];
static int g_model_count = 0;
static int g_texture_count = 0;
static std::string g_import_error;

static std::string portable_root()
{
    const char *env = std::getenv("MEGATURRICAN_CONFIG_DIR");
    if (env && env[0]) return env;
    char *base = SDL_GetBasePath();
    if (!base) return ".";
    std::string result(base);
    SDL_free(base);
    return result;
}
static void safe_copy(char *dst,size_t cap,const std::string &value)
{
    if(dst&&cap)std::snprintf(dst,cap,"%s",value.c_str());
}
static bool copy_model_bundle(const fs::path &source,const aiScene *scene,int index,fs::path &copied_model)
{
    std::error_code ec;
    const fs::path folder=fs::path(portable_root())/"Assets"/"Imported"/
        (std::string("asset_")+std::to_string(index+1)+"_"+source.stem().string());
    fs::create_directories(folder,ec);
    if(ec)return false;
    copied_model=folder/source.filename();
    fs::copy_file(source,copied_model,fs::copy_options::overwrite_existing,ec);
    if(ec)return false;
    if(!scene)return true;
    for(unsigned m=0;m<scene->mNumMaterials;m++){
        const aiMaterial *material=scene->mMaterials[m];
        const aiTextureType types[]={aiTextureType_DIFFUSE,aiTextureType_NORMALS,aiTextureType_EMISSIVE};
        for(aiTextureType type:types){
            for(unsigned t=0;t<material->GetTextureCount(type);t++){
                aiString texture;
                if(material->GetTexture(type,t,&texture)!=AI_SUCCESS)continue;
                const std::string rel=texture.C_Str();
                if(rel.empty()||rel[0]=='*')continue;
                fs::path from(rel);
                if(!from.is_absolute())from=source.parent_path()/from;
                if(!fs::exists(from,ec)||ec){ec.clear();continue;}
                fs::path to=folder/fs::path(rel);
                fs::create_directories(to.parent_path(),ec);
                if(ec){ec.clear();continue;}
                fs::copy_file(from,to,fs::copy_options::overwrite_existing,ec);
                ec.clear();
            }
        }
    }
    return true;
}
static void collect_material_textures(const aiScene *scene,ImportedModel &asset)
{
    if(!scene)return;
    for(unsigned i=0;i<scene->mNumMaterials;i++){
        const aiMaterial *m=scene->mMaterials[i];aiString v;
        if(!asset.diffuse[0]&&m->GetTexture(aiTextureType_DIFFUSE,0,&v)==AI_SUCCESS)
            safe_copy(asset.diffuse,sizeof(asset.diffuse),v.C_Str());
        if(!asset.normal[0]&&m->GetTexture(aiTextureType_NORMALS,0,&v)==AI_SUCCESS)
            safe_copy(asset.normal,sizeof(asset.normal),v.C_Str());
        if(!asset.emissive[0]&&m->GetTexture(aiTextureType_EMISSIVE,0,&v)==AI_SUCCESS)
            safe_copy(asset.emissive,sizeof(asset.emissive),v.C_Str());
    }
}
static void build_preview(const aiScene *scene,ImportedModel &asset,
                          const aiVector3D &minimum,const aiVector3D &maximum)
{
    const aiVector3D center=(minimum+maximum)*0.5f;
    const float extent=std::max({maximum.x-minimum.x,maximum.y-minimum.y,maximum.z-minimum.z,0.001f});
    const float scale=1.7f/extent;
    int written=0;
    for(unsigned m=0;m<scene->mNumMeshes&&written<kPreviewTriangles*3;m++){
        const aiMesh *mesh=scene->mMeshes[m];
        for(unsigned f=0;f<mesh->mNumFaces&&written<kPreviewTriangles*3;f++){
            const aiFace &face=mesh->mFaces[f];
            if(face.mNumIndices!=3)continue;
            for(unsigned k=0;k<3;k++){
                const aiVector3D &v=mesh->mVertices[face.mIndices[k]];
                asset.preview_xyz[written*3+0]=(v.x-center.x)*scale;
                asset.preview_xyz[written*3+1]=(v.y-center.y)*scale;
                asset.preview_xyz[written*3+2]=(v.z-center.z)*scale;
                ++written;
            }
        }
    }
    asset.preview_vertices=written;
}
} // namespace

extern "C" int mtlb_import_model(const char *path)
{
    g_import_error.clear();
    if(!path||!path[0]){g_import_error="No model file was selected.";return -1;}
    if(g_model_count>=kMaxImportedModels){g_import_error="The Maker model library is full.";return -1;}
    const fs::path source(path);
    std::string ext=source.extension().string();
    std::transform(ext.begin(),ext.end(),ext.begin(),[](unsigned char c){return (char)std::tolower(c);});
    if(ext!=".glb"&&ext!=".gltf"&&ext!=".obj"&&ext!=".fbx"){
        g_import_error="Supported model formats are GLB, GLTF, OBJ and FBX.";return -1;
    }
    Assimp::Importer importer;
    const aiScene *scene=importer.ReadFile(path,aiProcess_Triangulate|aiProcess_JoinIdenticalVertices|
        aiProcess_ImproveCacheLocality|aiProcess_SortByPType|aiProcess_ValidateDataStructure);
    if(!scene||!scene->mRootNode){
        g_import_error=importer.GetErrorString();
        if(g_import_error.empty())g_import_error="Assimp could not parse the selected model.";
        return -1;
    }
    ImportedModel asset;
    safe_copy(asset.name,sizeof(asset.name),source.filename().string());
    safe_copy(asset.path,sizeof(asset.path),source.string());
    safe_copy(asset.format,sizeof(asset.format),ext);
    aiVector3D lo(1e30f,1e30f,1e30f),hi(-1e30f,-1e30f,-1e30f);
    bool have_vertices=false;
    for(unsigned m=0;m<scene->mNumMeshes;m++){
        const aiMesh *mesh=scene->mMeshes[m];
        asset.bones+=mesh->mNumBones;
        for(unsigned f=0;f<mesh->mNumFaces;f++)if(mesh->mFaces[f].mNumIndices==3)asset.triangles++;
        for(unsigned v=0;v<mesh->mNumVertices;v++){
            const aiVector3D &p=mesh->mVertices[v];
            lo.x=std::min(lo.x,p.x);lo.y=std::min(lo.y,p.y);lo.z=std::min(lo.z,p.z);
            hi.x=std::max(hi.x,p.x);hi.y=std::max(hi.y,p.y);hi.z=std::max(hi.z,p.z);
            have_vertices=true;
        }
    }
    if(!have_vertices){g_import_error="The selected model contains no mesh vertices.";return -1;}
    asset.bounds[0]=hi.x-lo.x;asset.bounds[1]=hi.y-lo.y;asset.bounds[2]=hi.z-lo.z;
    collect_material_textures(scene,asset);
    build_preview(scene,asset,lo,hi);
    fs::path copied;
    if(copy_model_bundle(source,scene,g_model_count,copied))safe_copy(asset.path,sizeof(asset.path),copied.string());
    g_models[g_model_count]=asset;
    return g_model_count++;
}
extern "C" int mtlb_import_texture(const char *path)
{
    g_import_error.clear();
    if(!path||!path[0]){g_import_error="No texture file was selected.";return -1;}
    if(g_texture_count>=kMaxImportedTextures){g_import_error="The Maker texture library is full.";return -1;}
    SDL_Surface *surface=IMG_Load(path);
    if(!surface){g_import_error=IMG_GetError();if(g_import_error.empty())g_import_error="SDL_image could not load the texture.";return -1;}
    ImportedTexture texture;
    const fs::path source(path);
    safe_copy(texture.name,sizeof(texture.name),source.filename().string());
    safe_copy(texture.path,sizeof(texture.path),source.string());
    texture.width=surface->w;texture.height=surface->h;SDL_FreeSurface(surface);
    std::error_code ec;
    const fs::path folder=fs::path(portable_root())/"Assets"/"Imported"/"Textures";
    fs::create_directories(folder,ec);
    if(!ec){
        const fs::path target=folder/source.filename();
        fs::copy_file(source,target,fs::copy_options::overwrite_existing,ec);
        if(!ec)safe_copy(texture.path,sizeof(texture.path),target.string());
    }
    g_textures[g_texture_count]=texture;
    return g_texture_count++;
}
extern "C" int mtlb_imported_model_count(void){return g_model_count;}
extern "C" int mtlb_imported_model_info(int index,char *name,int name_capacity,char *path,int path_capacity,
    uint32_t *triangles,uint32_t *bones,float bounds_xyz[3],int *has_diffuse,int *has_normal,int *has_emissive,int *classification)
{
    if(index<0||index>=g_model_count)return 0;
    const ImportedModel &a=g_models[index];
    if(name)safe_copy(name,(size_t)std::max(0,name_capacity),a.name);
    if(path)safe_copy(path,(size_t)std::max(0,path_capacity),a.path);
    if(triangles)*triangles=a.triangles;if(bones)*bones=a.bones;
    if(bounds_xyz){bounds_xyz[0]=a.bounds[0];bounds_xyz[1]=a.bounds[1];bounds_xyz[2]=a.bounds[2];}
    if(has_diffuse)*has_diffuse=a.diffuse[0]!=0;
    if(has_normal)*has_normal=a.normal[0]!=0;
    if(has_emissive)*has_emissive=a.emissive[0]!=0;
    if(classification)*classification=a.classification;
    return 1;
}
extern "C" int mtlb_imported_model_preview(int index,float *xyz,int max_vertices)
{
    if(index<0||index>=g_model_count||!xyz||max_vertices<=0)return 0;
    const ImportedModel &a=g_models[index];const int count=std::min(a.preview_vertices,max_vertices);
    std::memcpy(xyz,a.preview_xyz.data(),(size_t)count*3u*sizeof(float));return count;
}
extern "C" void mtlb_imported_model_classify(int index,int classification)
{
    if(index>=0&&index<g_model_count)g_models[index].classification=std::max(0,std::min(4,classification));
}
extern "C" int mtlb_imported_texture_count(void){return g_texture_count;}
extern "C" int mtlb_imported_texture_info(int index,char *name,int name_capacity,char *path,int path_capacity,int *width,int *height)
{
    if(index<0||index>=g_texture_count)return 0;
    const ImportedTexture &t=g_textures[index];
    if(name)safe_copy(name,(size_t)std::max(0,name_capacity),t.name);
    if(path)safe_copy(path,(size_t)std::max(0,path_capacity),t.path);
    if(width)*width=t.width;if(height)*height=t.height;return 1;
}
extern "C" const char *mtlb_importer_last_error(void){return g_import_error.c_str();}
