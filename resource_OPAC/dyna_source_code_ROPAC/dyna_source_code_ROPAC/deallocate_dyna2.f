      subroutine deallocate_dyna2

	use muc_mod
	use LinkList_mod
	use INTOOI_MOD
	use VECTOR_MOD
 	integer error
	error=0
	
	deallocate(idnum)
	deallocate(SignalPreventFor)
	deallocate(GeoPreventFor)
	deallocate(llink)
	deallocate(TTimeOfBackLink)
	deallocate(ForToBackLink)
	deallocate(UturnFlag)
	deallocate(topocont)
	deallocate(UNodeOfBackLink)
      deallocate(jipick)
	deallocate(IntDestDwell)
	deallocate(nnpath)
	deallocate(NoOfIntDst)
	deallocate(IntDestZone)
	deallocate(IntDestPath)
	deallocate(jorigin)
      deallocate(vehclass)
      deallocate(vehclass2,stat=error)
	deallocate(iuserpath,stat=error)
      deallocate(penalty,stat=error)
      deallocate(BackPointr,stat=error)
      deallocate(movein,stat=error)
	deallocate(lt,stat=error)
	deallocate(ioc,stat=error)
	deallocate(connectivity,stat=error)
	deallocate(itag,stat=error)
	deallocate(s,stat=error)
	deallocate(nodenum,stat=error)
	deallocate(idnod,stat=error)
	deallocate(jdest,stat=error)
	deallocate(icurrnt,stat=error)
	deallocate(xpar,stat=error)
	deallocate(isec,stat=error)
	deallocate(stime,stat=error)
      deallocate(move,stat=error)  
	deallocate(iunod,stat=error)  
	deallocate(inlink,stat=error)

	if(allocated(origin))then  
	deallocate(origin)
	endif
	if(allocated(destination))then  
	deallocate(destination)
	endif
	if(allocated(MasterDest))then  
	deallocate(MasterDest)
	endif
	if(allocated(NoofGenLinksPerZone))then  		
	deallocate(NoofGenLinksPerZone)
	endif
	if(allocated(LinkNoInZone))then  
	deallocate(LinkNoInZone)
	endif

	deallocate(link_iden,stat=error)
	deallocate(BackToForLink,stat=error)

	if(allocated(VhcAtt_Array))then
 	do it=1,noofarcs
     	if(associated(VhcAtt_Array(it)%P))then
	  DEALLOCATE(VhcAtt_Array(it)%P,stat=error)
	  if(error.ne.0)then
	    write(911,*)"deallocate VhcAtt_1DArray vector error"
	    pause
	  endif
    	endif
	enddo
	deallocate(VhcAtt_Array)
	endif

      return
      end

