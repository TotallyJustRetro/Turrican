#include "mt_level_builder_importer.h"

#include <assimp/Importer.hpp>
#include <assimp/scene.h>
#include <assimp/postprocess.h>
#include <assimp/material.h>
#include <SDL.h>
#include <SDL_image.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;
namespace {
struct ImportedAnimation {
    char name[128] = {};
    float duration_seconds = 0.0f;
    uint32_t channels = 0;
};

struct ImportedModel {
    char name[128] = {};
    char path[1024] = {};
    char format[16] = {};
    char diffuse[512] = {};
    char normal[512] = {};
    char emissive[512] = {};
    std::string diffuse_path;
    float diffuse_color[4] = {0.72f,0.72f,0.72f,1.0f};
    uint32_t triangles = 0;
    uint32_t bones = 0;
    float bounds[3] = {0,0,0};
    int classification = 0;
    std::vector<float> preview_xyz;
    std::vector<float> preview_uv;
    std::vector<ImportedAnimation> animations;
};
struct ImportedTexture {
    char name[128] = {};
    char path[1024] = {};
    int width = 0;
    int height = 0;
};
static std::vector<ImportedModel> g_models;
static std::vector<ImportedTexture> g_textures;
static int g_model_count = 0;
static int g_texture_count = 0;
static bool g_models_scanned = false;
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
static std::string embedded_texture_extension(const aiTexture *texture)
{
    std::string ext=texture?texture->achFormatHint:"";
    std::transform(ext.begin(),ext.end(),ext.begin(),[](unsigned char c){return (char)std::tolower(c);});
    while(!ext.empty()&&ext.back()==' ')ext.pop_back();
    if(ext.empty())ext="png";
    return ext;
}

static fs::path embedded_texture_path(const fs::path &model_path,const aiTexture *texture,unsigned index)
{
    const std::string ext=(texture&&texture->mHeight>0)?"bmp":embedded_texture_extension(texture);
    return model_path.parent_path()/(std::string("embedded_")+std::to_string(index)+"."+ext);
}

static bool save_embedded_texture(const aiTexture *texture,const fs::path &destination)
{
    if(!texture||!texture->pcData||texture->mWidth==0)return false;
    std::error_code ec;
    fs::create_directories(destination.parent_path(),ec);
    if(ec)return false;
    if(texture->mHeight==0){
        std::ofstream out(destination,std::ios::binary|std::ios::trunc);
        if(!out)return false;
        out.write(reinterpret_cast<const char*>(texture->pcData),(std::streamsize)texture->mWidth);
        return out.good();
    }
    SDL_Surface *surface=SDL_CreateRGBSurfaceWithFormat(0,(int)texture->mWidth,(int)texture->mHeight,32,SDL_PIXELFORMAT_RGBA32);
    if(!surface)return false;
    if(SDL_MUSTLOCK(surface))SDL_LockSurface(surface);
    for(unsigned y=0;y<texture->mHeight;y++){
        auto *row=reinterpret_cast<Uint32*>(static_cast<Uint8*>(surface->pixels)+(size_t)y*(size_t)surface->pitch);
        for(unsigned x=0;x<texture->mWidth;x++){
            const aiTexel &src=texture->pcData[(size_t)y*texture->mWidth+x];
            row[x]=SDL_MapRGBA(surface->format,src.r,src.g,src.b,src.a);
        }
    }
    if(SDL_MUSTLOCK(surface))SDL_UnlockSurface(surface);
    const bool saved=SDL_SaveBMP(surface,destination.string().c_str())==0;
    SDL_FreeSurface(surface);
    return saved;
}

static bool copy_model_bundle(const fs::path &source,const aiScene *scene,int index,
                              fs::path &copied_model,std::string &copied_diffuse_path)
{
    std::error_code ec;
    const fs::path folder=fs::path(portable_root())/"Assets"/"Imported"/
        (std::string("asset_")+std::to_string(index+1)+"_"+source.stem().string());
    fs::create_directories(folder,ec);
    if(ec){g_import_error="Could not create the portable model asset folder: "+ec.message();return false;}
    copied_model=folder/source.filename();
    fs::copy_file(source,copied_model,fs::copy_options::overwrite_existing,ec);
    if(ec){g_import_error="Could not copy the model into Assets/Imported: "+ec.message();return false;}
    if(!scene)return true;

    // glTF sidecar buffers and images use relative URI paths. Preserve those
    // files beside the copied document so the portable library can reopen it.
    if(source.extension()==".gltf"){
        std::ifstream input(source,std::ios::binary);
        std::string json,line;
        if(input)while(std::getline(input,line)){json+=line;json.push_back('\n');}
        size_t cursor=0;
        while((cursor=json.find("\"uri\"",cursor))!=std::string::npos){
            const size_t colon=json.find(':',cursor+5);
            if(colon==std::string::npos)break;
            const size_t quote=json.find('"',colon+1);
            if(quote==std::string::npos)break;
            size_t end=quote+1;
            bool escaped=false;
            for(;end<json.size();end++){
                const char ch=json[end];
                if(!escaped&&ch=='"')break;
                if(!escaped&&ch=='\\')escaped=true;
                else escaped=false;
            }
            if(end>=json.size())break;
            const std::string uri=json.substr(quote+1,end-quote-1);
            cursor=end+1;
            if(uri.empty()||uri.rfind("data:",0)==0||uri.find("://")!=std::string::npos)continue;
            fs::path relative(uri);
            if(relative.is_absolute()||relative.has_root_name())continue;
            relative=relative.lexically_normal();
            bool unsafe=false;
            for(const auto &part:relative)if(part=="..")unsafe=true;
            if(unsafe){
                g_import_error="The glTF references a file outside its source folder; move its dependencies beside the model before importing.";
                return false;
            }
            const fs::path from=source.parent_path()/relative;
            if(!fs::is_regular_file(from,ec)||ec){
                ec.clear();
                g_import_error="A glTF dependency could not be found: "+from.string();
                return false;
            }
            const fs::path to=folder/relative;
            fs::create_directories(to.parent_path(),ec);
            if(ec){g_import_error="Could not create a glTF dependency folder: "+ec.message();return false;}
            fs::copy_file(from,to,fs::copy_options::overwrite_existing,ec);
            if(ec){g_import_error="Could not copy a glTF dependency: "+ec.message();return false;}
        }
    }

    // OBJ material libraries are external sidecars. The texture files
    // themselves are copied below from Assimp's material references.
    if(source.extension()==".obj"){
        std::ifstream input(source);
        std::string line;
        while(std::getline(input,line)){
            if(line.rfind("mtllib ",0)!=0)continue;
            const std::string libraries=line.substr(7);
            size_t pos=0;
            while(pos<libraries.size()){
                while(pos<libraries.size()&&std::isspace((unsigned char)libraries[pos]))++pos;
                const size_t end=libraries.find_first_of(" \t\r",pos);
                const std::string library=libraries.substr(pos,end==std::string::npos?std::string::npos:end-pos);
                if(!library.empty()){
                    const fs::path relative(library);
                    if(relative.is_absolute()||relative.has_root_name())continue;
                    const fs::path from=source.parent_path()/relative;
                    if(fs::is_regular_file(from,ec)&&!ec){
                        const fs::path target=folder/relative;
                        fs::create_directories(target.parent_path(),ec);
                        if(ec){g_import_error="Could not create OBJ material folder: "+ec.message();return false;}
                        fs::copy_file(from,target,fs::copy_options::overwrite_existing,ec);
                        if(ec){g_import_error="Could not copy OBJ material library: "+ec.message();return false;}
                    }else{
                        ec.clear();
                        g_import_error="An OBJ material library could not be found: "+from.string();
                        return false;
                    }
                }
                if(end==std::string::npos)break;
                pos=end+1;
            }
        }
    }

    const aiTextureType types[]={aiTextureType_BASE_COLOR,aiTextureType_DIFFUSE,aiTextureType_NORMALS,aiTextureType_EMISSIVE};
    for(unsigned m=0;m<scene->mNumMaterials;m++){
        const aiMaterial *material=scene->mMaterials[m];
        for(aiTextureType type:types){
            for(unsigned t=0;t<material->GetTextureCount(type);t++){
                aiString texture;
                if(material->GetTexture(type,t,&texture)!=AI_SUCCESS)continue;
                const std::string rel=texture.C_Str();
                if(rel.empty())continue;
                fs::path target;
                if(rel[0]=='*'){
                    const int embedded=std::atoi(rel.c_str()+1);
                    if(embedded<0||(unsigned)embedded>=scene->mNumTextures)continue;
                    target=embedded_texture_path(copied_model,scene->mTextures[embedded],(unsigned)embedded);
                    if(!fs::exists(target,ec)&&!save_embedded_texture(scene->mTextures[embedded],target)){
                        ec.clear();
                        continue;
                    }
                }else{
                    fs::path relative(rel);
                    fs::path from=relative.is_absolute()?relative:(source.parent_path()/relative);
                    if(!fs::exists(from,ec)||ec){ec.clear();continue;}
                    if(relative.is_absolute()||relative.has_root_name())relative=fs::path("textures")/from.filename();
                    relative=relative.lexically_normal();
                    bool unsafe=false;
                    for(const auto &part:relative)if(part=="..")unsafe=true;
                    if(unsafe)relative=fs::path("textures")/from.filename();
                    target=folder/relative;
                    fs::create_directories(target.parent_path(),ec);
                    if(ec){ec.clear();continue;}
                    fs::copy_file(from,target,fs::copy_options::overwrite_existing,ec);
                    if(ec){ec.clear();continue;}
                }
                if(copied_diffuse_path.empty()&&(type==aiTextureType_BASE_COLOR||type==aiTextureType_DIFFUSE))
                    copied_diffuse_path=target.string();
            }
        }
    }
    return true;
}

static std::string resolve_diffuse_texture(const aiScene *scene,const fs::path &model_path)
{
    if(!scene)return {};
    const aiTextureType types[]={aiTextureType_BASE_COLOR,aiTextureType_DIFFUSE};
    for(unsigned m=0;m<scene->mNumMaterials;m++){
        const aiMaterial *material=scene->mMaterials[m];
        for(aiTextureType type:types){
            if(material->GetTextureCount(type)==0)continue;
            aiString texture;
            if(material->GetTexture(type,0,&texture)!=AI_SUCCESS)continue;
            const std::string rel=texture.C_Str();
            if(rel.empty())continue;
            fs::path resolved;
            if(rel[0]=='*'){
                const int embedded=std::atoi(rel.c_str()+1);
                if(embedded<0||(unsigned)embedded>=scene->mNumTextures)continue;
                resolved=embedded_texture_path(model_path,scene->mTextures[embedded],(unsigned)embedded);
            }else{
                resolved=fs::path(rel);
                if(!resolved.is_absolute())resolved=model_path.parent_path()/resolved;
            }
            std::error_code ec;
            if(fs::is_regular_file(resolved,ec)&&!ec)return resolved.string();
        }
    }
    return {};
}

static void collect_material_textures(const aiScene *scene,ImportedModel &asset)
{
    if(!scene)return;
    for(unsigned i=0;i<scene->mNumMaterials;i++){
        const aiMaterial *material=scene->mMaterials[i];
        aiString texture;
        if(!asset.diffuse[0]){
            if(material->GetTexture(aiTextureType_BASE_COLOR,0,&texture)==AI_SUCCESS||
               material->GetTexture(aiTextureType_DIFFUSE,0,&texture)==AI_SUCCESS)
                safe_copy(asset.diffuse,sizeof(asset.diffuse),texture.C_Str());
        }
        if(!asset.normal[0]&&material->GetTexture(aiTextureType_NORMALS,0,&texture)==AI_SUCCESS)
            safe_copy(asset.normal,sizeof(asset.normal),texture.C_Str());
        if(!asset.emissive[0]&&material->GetTexture(aiTextureType_EMISSIVE,0,&texture)==AI_SUCCESS)
            safe_copy(asset.emissive,sizeof(asset.emissive),texture.C_Str());
        aiColor4D color;
        if(material->Get(AI_MATKEY_COLOR_DIFFUSE,color)==AI_SUCCESS){
            asset.diffuse_color[0]=color.r;
            asset.diffuse_color[1]=color.g;
            asset.diffuse_color[2]=color.b;
            asset.diffuse_color[3]=color.a;
        }
    }
}

static void collect_animations(const aiScene *scene,ImportedModel &asset)
{
    if(!scene)return;
    asset.animations.clear();
    asset.animations.reserve(scene->mNumAnimations);
    for(unsigned i=0;i<scene->mNumAnimations;i++){
        const aiAnimation *source=scene->mAnimations[i];
        if(!source)continue;
        ImportedAnimation animation;
        const std::string name=source->mName.length?source->mName.C_Str():("Animation "+std::to_string(i+1));
        safe_copy(animation.name,sizeof(animation.name),name);
        const double ticks=source->mTicksPerSecond>0.0?source->mTicksPerSecond:25.0;
        animation.duration_seconds=(float)(source->mDuration/ticks);
        animation.channels=source->mNumChannels+source->mNumMeshChannels+source->mNumMorphMeshChannels;
        asset.animations.push_back(animation);
    }
}

static void build_preview(const aiScene *scene,ImportedModel &asset,
                          const aiVector3D &minimum,const aiVector3D &maximum)
{
    const aiVector3D center=(minimum+maximum)*0.5f;
    const float extent=std::max({maximum.x-minimum.x,maximum.y-minimum.y,maximum.z-minimum.z,0.001f});
    const float scale=1.7f/extent;
    asset.preview_xyz.clear();
    asset.preview_uv.clear();
    asset.preview_xyz.reserve((size_t)asset.triangles*9u);
    asset.preview_uv.reserve((size_t)asset.triangles*6u);
    for(unsigned m=0;m<scene->mNumMeshes;m++){
        const aiMesh *mesh=scene->mMeshes[m];
        for(unsigned f=0;f<mesh->mNumFaces;f++){
            const aiFace &face=mesh->mFaces[f];
            if(face.mNumIndices!=3)continue;
            for(unsigned k=0;k<3;k++){
                const unsigned index=face.mIndices[k];
                const aiVector3D &v=mesh->mVertices[index];
                asset.preview_xyz.push_back((v.x-center.x)*scale);
                asset.preview_xyz.push_back((v.y-center.y)*scale);
                asset.preview_xyz.push_back((v.z-center.z)*scale);
                if(mesh->HasTextureCoords(0)){
                    asset.preview_uv.push_back(mesh->mTextureCoords[0][index].x);
                    asset.preview_uv.push_back(mesh->mTextureCoords[0][index].y);
                }else{
                    asset.preview_uv.push_back(0.0f);
                    asset.preview_uv.push_back(0.0f);
                }
            }
        }
    }
}

static std::string model_metadata_path(const ImportedModel &asset)
{
    return (fs::path(asset.path).parent_path()/"maker-model.ini").string();
}

static void save_model_metadata(const ImportedModel &asset)
{
    const fs::path folder=fs::path(asset.path).parent_path();
    std::error_code ec;
    fs::create_directories(folder,ec);
    if(ec)return;
    const fs::path meta=folder/"maker-model.ini";
    FILE *file=std::fopen(meta.string().c_str(),"wb");
    if(!file)return;
    fs::path relative;
    if(!asset.diffuse_path.empty())relative=fs::path(asset.diffuse_path).lexically_relative(folder);
    std::fprintf(file,"MT_MODEL 1\nclassification=%d\ndiffuse=%s\n",
        asset.classification,relative.generic_string().c_str());
    std::fclose(file);
}

static void load_model_metadata(ImportedModel &asset)
{
    const fs::path folder=fs::path(asset.path).parent_path();
    const std::string metadata=model_metadata_path(asset);
    FILE *file=std::fopen(metadata.c_str(),"rb");
    if(!file)return;
    char line[2048];
    while(std::fgets(line,sizeof(line),file)){
        line[std::strcspn(line,"\r\n")]=0;
        int value=0;
        if(std::sscanf(line,"classification=%d",&value)==1)
            asset.classification=std::max(0,std::min(4,value));
        else if(std::strncmp(line,"diffuse=",8)==0){
            const std::string relative=line+8;
            if(!relative.empty()){
                fs::path diffuse(relative);
                if(!diffuse.is_absolute())diffuse=folder/diffuse;
                std::error_code ec;
                if(fs::is_regular_file(diffuse,ec)&&!ec)asset.diffuse_path=diffuse.string();
            }
        }
    }
    std::fclose(file);
}

} // namespace

static int import_model_internal(const char *path, bool copy_into_library)
{
    g_import_error.clear();
    if(!path||!path[0]){g_import_error="No model file was selected.";return -1;}
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
    collect_animations(scene,asset);
    build_preview(scene,asset,lo,hi);

    if(copy_into_library){
        fs::path copied_model;
        std::string copied_diffuse;
        if(!copy_model_bundle(source,scene,g_model_count,copied_model,copied_diffuse)){
            if(g_import_error.empty())g_import_error="The model or one of its required files could not be copied into Assets/Imported.";
            return -1;
        }
        safe_copy(asset.path,sizeof(asset.path),copied_model.string());
        asset.diffuse_path=copied_diffuse;
    }else{
        asset.diffuse_path=resolve_diffuse_texture(scene,source);
        load_model_metadata(asset);
    }
    g_models.push_back(asset);
    const int index=g_model_count++;
    if(copy_into_library){
        save_model_metadata(g_models.back());
        const fs::path stored(g_models.back().path);
        std::error_code ec;
        if(!fs::is_regular_file(stored,ec)||ec||fs::file_size(stored,ec)==0||ec){
            g_models.pop_back();
            --g_model_count;
            g_import_error="The model did not persist to the portable Assets/Imported folder.";
            return -1;
        }
    }
    return index;
}

extern "C" int mtlb_import_model(const char *path)
{
    return import_model_internal(path,true);
}

extern "C" int mtlb_imported_model_scan(void)
{
    if(g_models_scanned)return g_model_count;
    g_models_scanned=true;
    const fs::path root=fs::path(portable_root())/"Assets"/"Imported";
    std::error_code ec;
    if(!fs::exists(root,ec)||ec)return g_model_count;
    std::vector<fs::path> candidates;
    for(fs::recursive_directory_iterator it(root,ec),end;it!=end;it.increment(ec)){
        if(ec){ec.clear();continue;}
        if(!it->is_regular_file(ec)){ec.clear();continue;}
        std::string ext=it->path().extension().string();
        std::transform(ext.begin(),ext.end(),ext.begin(),[](unsigned char c){return (char)std::tolower(c);});
        if(ext==".glb"||ext==".gltf"||ext==".obj"||ext==".fbx")
            candidates.push_back(it->path());
    }
    auto asset_order=[](const fs::path &path){
        int order=0x7fffffff;
        const std::string folder=path.parent_path().filename().string();
        if(std::sscanf(folder.c_str(),"asset_%d_",&order)!=1)order=0x7fffffff;
        return order;
    };
    std::stable_sort(candidates.begin(),candidates.end(),[&](const fs::path &a,const fs::path &b){
        const int oa=asset_order(a),ob=asset_order(b);
        if(oa!=ob)return oa<ob;
        return a.generic_string()<b.generic_string();
    });
    for(const fs::path &candidate:candidates)
        import_model_internal(candidate.string().c_str(),false);
    return g_model_count;
}

extern "C" int mtlb_import_texture(const char *path)
{
    g_import_error.clear();
    if(!path||!path[0]){g_import_error="No texture file was selected.";return -1;}
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
    if(ec){g_import_error="Could not create the portable texture folder: "+ec.message();return -1;}
    const fs::path target=folder/source.filename();
    fs::copy_file(source,target,fs::copy_options::overwrite_existing,ec);
    if(ec){g_import_error="Could not copy the texture into Assets/Imported/Textures: "+ec.message();return -1;}
    safe_copy(texture.path,sizeof(texture.path),target.string());
    g_textures.push_back(texture);
    return g_texture_count++;
}
extern "C" int mtlb_imported_model_count(void){return g_model_count;}
extern "C" int mtlb_imported_model_info(int index,char *name,int name_capacity,char *path,int path_capacity,
    uint32_t *triangles,uint32_t *bones,float bounds_xyz[3],int *has_diffuse,int *has_normal,int *has_emissive,int *classification)
{
    if(index<0||index>=g_model_count)return 0;
    const ImportedModel &a=g_models[(size_t)index];
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
extern "C" int mtlb_imported_model_preview(int index,float *xyz,float *uv,int max_vertices)
{
    if(index<0||index>=g_model_count||!xyz||max_vertices<=0)return 0;
    const ImportedModel &asset=g_models[(size_t)index];
    const int count=std::min((int)(asset.preview_xyz.size()/3u),max_vertices);
    if(count>0){
        std::memcpy(xyz,asset.preview_xyz.data(),(size_t)count*3u*sizeof(float));
        if(uv&&asset.preview_uv.size()>=(size_t)count*2u)
            std::memcpy(uv,asset.preview_uv.data(),(size_t)count*2u*sizeof(float));
    }
    return count;
}
extern "C" int mtlb_imported_model_diffuse_path(int index,char *path,int capacity)
{
    if(index<0||index>=g_model_count)return 0;
    const std::string &value=g_models[(size_t)index].diffuse_path;
    if(path&&capacity>0)safe_copy(path,(size_t)capacity,value);
    return value.empty()?0:1;
}
extern "C" int mtlb_imported_model_base_color(int index,float rgba[4])
{
    if(index<0||index>=g_model_count)return 0;
    if(rgba)std::memcpy(rgba,g_models[(size_t)index].diffuse_color,sizeof(float)*4u);
    return 1;
}
extern "C" int mtlb_imported_model_animation_count(int index)
{
    if(index<0||index>=g_model_count)return 0;
    return (int)g_models[(size_t)index].animations.size();
}
extern "C" int mtlb_imported_model_animation_info(int index,int animation,char *name,int name_capacity,
                                                    float *duration_seconds,uint32_t *channels)
{
    if(index<0||index>=g_model_count)return 0;
    const ImportedModel &asset=g_models[(size_t)index];
    if(animation<0||(size_t)animation>=asset.animations.size())return 0;
    const ImportedAnimation &clip=asset.animations[(size_t)animation];
    if(name)safe_copy(name,(size_t)std::max(0,name_capacity),clip.name);
    if(duration_seconds)*duration_seconds=clip.duration_seconds;
    if(channels)*channels=clip.channels;
    return 1;
}
extern "C" void mtlb_imported_model_classify(int index,int classification)
{
    if(index>=0&&index<g_model_count){
        ImportedModel &asset=g_models[(size_t)index];
        asset.classification=std::max(0,std::min(4,classification));
        save_model_metadata(asset);
    }
}
extern "C" int mtlb_imported_texture_count(void){return g_texture_count;}
extern "C" int mtlb_imported_texture_info(int index,char *name,int name_capacity,char *path,int path_capacity,int *width,int *height)
{
    if(index<0||index>=g_texture_count)return 0;
    const ImportedTexture &t=g_textures[(size_t)index];
    if(name)safe_copy(name,(size_t)std::max(0,name_capacity),t.name);
    if(path)safe_copy(path,(size_t)std::max(0,path_capacity),t.path);
    if(width)*width=t.width;if(height)*height=t.height;return 1;
}
extern "C" const char *mtlb_importer_last_error(void){return g_import_error.c_str();}
